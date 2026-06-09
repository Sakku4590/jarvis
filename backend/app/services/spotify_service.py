"""Spotify service.

Wraps the Spotify Web API behind an interface so tests use a fake. The real
implementation loads encrypted credentials per user, refreshes the access token
when it is near expiry or on a 401, and maps Spotify HTTP errors to clean
SpotifyError exceptions. httpx is used directly; no SDK.
"""

import time
from abc import ABC, abstractmethod

import httpx

from app.core.logging import get_logger
from app.integrations.credential_store import CredentialStore, get_credential_store
from app.integrations.spotify_oauth import refresh_access_token

log = get_logger(__name__)

_API = "https://api.spotify.com/v1"


class SpotifyError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


class NotConnected(SpotifyError):
    def __init__(self) -> None:
        super().__init__("not_connected", "Spotify is not connected; authorize first")


class SpotifyService(ABC):
    @abstractmethod
    async def search(self, user_id: str, query: str, type_: str = "track",
                     limit: int = 5) -> dict: ...

    @abstractmethod
    async def play(self, user_id: str, query: str | None = None,
                   uris: list[str] | None = None,
                   context_uri: str | None = None) -> dict: ...

    @abstractmethod
    async def pause(self, user_id: str) -> dict: ...

    @abstractmethod
    async def skip(self, user_id: str, direction: str = "next") -> dict: ...

    @abstractmethod
    async def create_playlist(self, user_id: str, name: str, public: bool = False,
                              track_uris: list[str] | None = None,
                              query: str | None = None) -> dict: ...


class SpotifyApiService(SpotifyService):
    def __init__(self, store: CredentialStore | None = None) -> None:
        self.store = store or get_credential_store()

    async def _token(self, user_id: str, force: bool = False) -> dict:
        token = await self.store.load(user_id, "spotify")
        if token is None:
            raise NotConnected()
        expiry = token.get("expiry")
        near_expiry = isinstance(expiry, (int, float)) and expiry - time.time() < 60
        if force or near_expiry:
            token = await refresh_access_token(token)
            await self.store.save(user_id, "spotify", token)
        return token

    async def _request(self, user_id: str, method: str, path: str, **kw) -> dict:
        token = await self._token(user_id)
        async with httpx.AsyncClient(base_url=_API, timeout=15) as c:
            headers = {"Authorization": f"Bearer {token['access_token']}"}
            resp = await c.request(method, path, headers=headers, **kw)
            if resp.status_code == 401:
                token = await self._token(user_id, force=True)
                headers = {"Authorization": f"Bearer {token['access_token']}"}
                resp = await c.request(method, path, headers=headers, **kw)
        self._check(resp)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    @staticmethod
    def _check(resp: httpx.Response) -> None:
        if resp.is_success:
            return
        code = resp.status_code
        if code == 401:
            raise SpotifyError("unauthorized", "authorization expired; reconnect")
        if code == 403:
            raise SpotifyError("forbidden", "action not allowed (Spotify Premium may be required)")
        if code == 404:
            raise SpotifyError("no_active_device", "no active Spotify device found")
        if code == 429:
            raise SpotifyError("rate_limited", "Spotify rate limit exceeded")
        raise SpotifyError("api_error", f"Spotify API error {code}")

    # --- operations ---

    async def search(self, user_id, query, type_="track", limit=5) -> dict:
        data = await self._request(user_id, "GET", "/search",
                                   params={"q": query, "type": type_, "limit": limit})
        items = data.get(f"{type_}s", {}).get("items", [])
        return {"query": query, "results": [
            {"name": it.get("name"), "uri": it.get("uri"),
             "artist": (it.get("artists") or [{}])[0].get("name")}
            for it in items]}

    async def play(self, user_id, query=None, uris=None, context_uri=None) -> dict:
        if query and not uris and not context_uri:
            found = await self.search(user_id, query, "track", 1)
            if not found["results"]:
                raise SpotifyError("not_found", f"no track found for '{query}'")
            uris = [found["results"][0]["uri"]]
        body: dict = {}
        if uris:
            body["uris"] = uris
        elif context_uri:
            body["context_uri"] = context_uri
        await self._request(user_id, "PUT", "/me/player/play", json=body)
        return {"playing": True, "uris": uris, "context_uri": context_uri}

    async def pause(self, user_id) -> dict:
        await self._request(user_id, "PUT", "/me/player/pause")
        return {"paused": True}

    async def skip(self, user_id, direction="next") -> dict:
        endpoint = "/me/player/previous" if direction == "previous" else "/me/player/next"
        await self._request(user_id, "POST", endpoint)
        return {"skipped": direction}

    async def create_playlist(self, user_id, name, public=False,
                              track_uris=None, query=None) -> dict:
        me = await self._request(user_id, "GET", "/me")
        spotify_user_id = me.get("id")
        playlist = await self._request(
            user_id, "POST", f"/users/{spotify_user_id}/playlists",
            json={"name": name, "public": public,
                  "description": "Created by Jarvis"})
        pid = playlist.get("id")

        if query and not track_uris:
            found = await self.search(user_id, query, "track", 10)
            track_uris = [r["uri"] for r in found["results"]]
        if track_uris:
            await self._request(user_id, "POST", f"/playlists/{pid}/tracks",
                                json={"uris": track_uris})
        return {"playlist_id": pid, "name": name,
                "url": playlist.get("external_urls", {}).get("spotify"),
                "tracks_added": len(track_uris or [])}


def get_spotify_service() -> SpotifyService:
    return SpotifyApiService()
