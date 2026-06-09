"""Spotify OAuth (Authorization Code flow).

Uses httpx directly (no SDK). The authorize-URL construction is a pure function
so it is testable without network; code exchange and refresh hit the token
endpoint at runtime. State is kept in process memory (fine for single-instance;
use Redis for multi-instance).
"""

import secrets
import time
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_AUTH_URL = "https://accounts.spotify.com/authorize"
_TOKEN_URL = "https://accounts.spotify.com/api/token"
_PENDING_STATES: dict[str, str] = {}


class OAuthError(Exception):
    pass


def _require_config():
    s = get_settings()
    if not s.spotify_client_id or not s.spotify_client_secret:
        raise OAuthError("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET are not configured")
    return s


def build_authorize_url(client_id: str, redirect_uri: str,
                        scopes: list[str], state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": " ".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def authorize_url(user_id: str) -> str:
    s = _require_config()
    state = secrets.token_urlsafe(24)
    from app.integrations.oauth_state import put_state

    put_state(state, "spotify", user_id)
    return build_authorize_url(
        s.spotify_client_id, s.spotify_redirect_uri, s.spotify_scope_list, state)


def consume_state(state: str) -> str:
    from app.integrations.oauth_state import take_state

    user_id = take_state(state, "spotify")
    if user_id is None:
        raise OAuthError("invalid or expired OAuth state")
    return user_id


def _token_dict(payload: dict, fallback_refresh: str | None = None) -> dict:
    s = get_settings()
    expiry = time.time() + int(payload.get("expires_in", 3600))
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token") or fallback_refresh,
        "token_uri": _TOKEN_URL,
        "client_id": s.spotify_client_id,
        "client_secret": s.spotify_client_secret,
        "scopes": (payload.get("scope") or "").split() or s.spotify_scope_list,
        "expiry": expiry,  # epoch seconds
    }


async def exchange_code(state: str, code: str) -> tuple[str, dict]:
    s = _require_config()
    user_id = consume_state(state)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": s.spotify_redirect_uri,
        "client_id": s.spotify_client_id,
        "client_secret": s.spotify_client_secret,
    }
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.post(_TOKEN_URL, data=data)
    if resp.status_code != 200:
        raise OAuthError(f"token exchange failed: {resp.status_code} {resp.text[:200]}")
    return user_id, _token_dict(resp.json())


async def refresh_access_token(token: dict) -> dict:
    s = get_settings()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": token.get("refresh_token"),
        "client_id": token.get("client_id") or s.spotify_client_id,
        "client_secret": token.get("client_secret") or s.spotify_client_secret,
    }
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.post(_TOKEN_URL, data=data)
    if resp.status_code != 200:
        raise OAuthError(f"token refresh failed: {resp.status_code}")
    return _token_dict(resp.json(), fallback_refresh=token.get("refresh_token"))
