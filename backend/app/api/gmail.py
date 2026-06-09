"""Gmail API: OAuth setup and the email task endpoint.

OAuth flow:
  1. GET  /integrations/gmail/authorize?user_id=...  -> { authorize_url }
     The user opens that URL and grants access.
  2. GET  /integrations/gmail/callback?code=...&state=...
     Google redirects here; we exchange the code and store encrypted tokens.
  3. GET  /integrations/gmail/status?user_id=...      -> { connected }

Then POST /email/task delegates a natural-language email task to the agent.
"""

from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.agents.gmail_agent import GmailAgent, get_gmail_agent
from app.core.logging import get_logger
from app.integrations.credential_store import get_credential_store
from app.integrations.google_oauth import OAuthError, authorize_url, exchange_code

router = APIRouter(tags=["gmail"])
log = get_logger(__name__)


@lru_cache
def _agent() -> GmailAgent:
    return get_gmail_agent()


@router.get("/integrations/gmail/authorize")
async def gmail_authorize(user_id: str = Query(...)) -> dict:
    try:
        return {"authorize_url": authorize_url(user_id)}
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/integrations/gmail/callback")
async def gmail_callback(
    code: str | None = None, state: str | None = None, error: str | None = None
) -> JSONResponse:
    if error:
        return JSONResponse({"status": "error", "detail": error}, status_code=400)
    if not code or not state:
        return JSONResponse({"status": "error", "detail": "missing code or state"},
                            status_code=400)
    try:
        user_id, token = exchange_code(state, code)
        await get_credential_store().save(user_id, "gmail", token)
    except OAuthError as exc:
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        log.warning("gmail.callback_failed", error=str(exc))
        return JSONResponse({"status": "error", "detail": "could not store credentials"},
                            status_code=500)
    return JSONResponse({"status": "connected", "user_id": user_id})


@router.get("/integrations/gmail/status")
async def gmail_status(user_id: str = Query(...)) -> dict:
    token = await get_credential_store().load(user_id, "gmail")
    return {"connected": token is not None,
            "scopes": (token or {}).get("scopes", [])}


class EmailTaskRequest(BaseModel):
    user_id: str
    instruction: str
    approved: bool = False


@router.post("/email/task")
async def email_task(req: EmailTaskRequest) -> dict:
    return await _agent().arun(req.user_id, req.instruction, req.approved)
