"""Google OAuth helpers.

Builds the authorization URL, exchanges the callback code for tokens, and
serializes Google credentials to/from the dict we store. google libraries are
imported lazily so the rest of the system imports without them.

CSRF note: a random `state` is issued at authorize time and checked at callback.
This implementation keeps pending states in process memory, which is fine for a
single-instance single-user deployment; a multi-instance deployment should keep
state in Redis.
"""

import secrets

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

# state -> user_id, issued at authorize, consumed at callback.
_PENDING_STATES: dict[str, str] = {}


class OAuthError(Exception):
    pass


def _client_config() -> dict:
    s = get_settings()
    if not s.google_client_id or not s.google_client_secret:
        raise OAuthError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not configured")
    return {
        "web": {
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [s.google_oauth_redirect_uri],
        }
    }


def _build_flow(state: str | None = None):
    from google_auth_oauthlib.flow import Flow  # lazy

    s = get_settings()
    flow = Flow.from_client_config(
        _client_config(),
        scopes=s.gmail_scope_list,
        redirect_uri=s.google_oauth_redirect_uri,
        state=state,
    )
    # We are a confidential client (client secret + "web" app type), so we use
    # plain authorization-code, not PKCE. The authorize and callback steps build
    # separate Flow objects and cannot share a PKCE code_verifier, which would
    # otherwise cause "invalid_grant: Missing code verifier" at token exchange.
    # Disabling auto-generated PKCE keeps the two steps consistent.
    flow.autogenerate_code_verifier = False
    if getattr(flow, "oauth2session", None) is not None:
        flow.oauth2session._code_verifier = None
    return flow


def authorize_url(user_id: str) -> str:
    state = secrets.token_urlsafe(24)
    from app.integrations.oauth_state import put_state

    put_state(state, "gmail", user_id)
    flow = _build_flow(state=state)
    url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent")
    return url


def consume_state(state: str) -> str:
    from app.integrations.oauth_state import take_state

    user_id = take_state(state, "gmail")
    if user_id is None:
        raise OAuthError("invalid or expired OAuth state")
    return user_id


def exchange_code(state: str, code: str) -> tuple[str, dict]:
    """Returns (user_id, token_dict). Raises OAuthError on failure."""
    user_id = consume_state(state)
    flow = _build_flow(state=state)
    try:
        flow.fetch_token(code=code)
    except Exception as exc:  # noqa: BLE001 - many google error types
        raise OAuthError(f"token exchange failed: {exc}") from exc
    return user_id, creds_to_dict(flow.credentials)


def creds_to_dict(creds) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }


def credentials_from_dict(token: dict):
    from google.oauth2.credentials import Credentials  # lazy

    return Credentials(
        token=token.get("token"),
        refresh_token=token.get("refresh_token"),
        token_uri=token.get("token_uri"),
        client_id=token.get("client_id"),
        client_secret=token.get("client_secret"),
        scopes=token.get("scopes"),
    )
