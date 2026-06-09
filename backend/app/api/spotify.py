"""Spotify API: OAuth setup and the music task endpoint.

  GET  /integrations/spotify/authorize?user_id=...  -> { authorize_url }
  GET  /integrations/spotify/callback?code=&state=  -> stores encrypted tokens
  GET  /integrations/spotify/status?user_id=...     -> { connected }
  POST /music/task                                  -> run the Spotify agent
"""

from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.agents.spotify_agent import SpotifyAgent, get_spotify_agent
from app.core.logging import get_logger
from app.integrations.credential_store import get_credential_store
from app.integrations.spotify_oauth import OAuthError, authorize_url, exchange_code

router = APIRouter(tags=["spotify"])
log = get_logger(__name__)


@lru_cache
def _agent() -> SpotifyAgent:
    return get_spotify_agent()


@router.get("/integrations/spotify/authorize")
async def spotify_authorize(user_id: str = Query(...)) -> dict:
    try:
        return {"authorize_url": authorize_url(user_id)}
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/integrations/spotify/callback")
async def spotify_callback(
    code: str | None = None, state: str | None = None, error: str | None = None
) -> JSONResponse:
    if error:
        return JSONResponse({"status": "error", "detail": error}, status_code=400)
    if not code or not state:
        return JSONResponse({"status": "error", "detail": "missing code or state"},
                            status_code=400)
    try:
        user_id, token = await exchange_code(state, code)
        await get_credential_store().save(user_id, "spotify", token)
    except OAuthError as exc:
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        log.warning("spotify.callback_failed", error=str(exc))
        return JSONResponse({"status": "error", "detail": "could not store credentials"},
                            status_code=500)
    return JSONResponse({"status": "connected", "user_id": user_id})


@router.get("/integrations/spotify/status")
async def spotify_status(user_id: str = Query(...)) -> dict:
    token = await get_credential_store().load(user_id, "spotify")
    return {"connected": token is not None,
            "scopes": (token or {}).get("scopes", [])}


class MusicTaskRequest(BaseModel):
    user_id: str
    instruction: str
    approved: bool = False


@router.post("/music/task")
async def music_task(req: MusicTaskRequest) -> dict:
    return await _agent().arun(req.user_id, req.instruction, req.approved)
