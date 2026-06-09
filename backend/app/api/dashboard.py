"""Dashboard support API.

Read-only endpoints that back the Next.js dashboard:
  GET /dashboard/agents?user_id=...  -> capability/agent/integration status
  GET /dashboard/activity?limit=...  -> recent tool calls
  GET /dashboard/tasks?limit=...     -> recent task runs
"""

from fastapi import APIRouter, Query

from app.core.config import get_settings
from app.integrations.credential_store import get_credential_store
from app.observability.activity import get_activity_store

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# capability -> how it authenticates
_AGENTS = [
    {"capability": "memory", "label": "Memory", "auth": "none"},
    {"capability": "file", "label": "File", "auth": "none"},
    {"capability": "code", "label": "Coding", "auth": "none"},
    {"capability": "browser", "label": "Browser", "auth": "none"},
    {"capability": "email", "label": "Email (Gmail)", "auth": "oauth", "provider": "gmail"},
    {"capability": "music", "label": "Spotify", "auth": "oauth", "provider": "spotify"},
    {"capability": "messaging", "label": "WhatsApp", "auth": "app"},
]


@router.get("/agents")
async def agents(user_id: str | None = Query(None)) -> dict:
    s = get_settings()
    store = get_credential_store()
    out = []
    for a in _AGENTS:
        connected: bool | None = None
        if a["auth"] == "oauth":
            connected = bool(user_id) and (
                await store.load(user_id, a["provider"]) is not None)
        elif a["auth"] == "app":  # whatsapp / twilio
            connected = bool(s.twilio_account_sid and s.twilio_auth_token
                             and s.twilio_whatsapp_from)
        else:
            connected = True  # no external auth needed
        out.append({**a, "connected": connected})
    return {"agents": out}


@router.get("/activity")
async def activity(limit: int = 50) -> dict:
    return {"tools": get_activity_store().recent_tools(limit)}


@router.get("/tasks")
async def tasks(limit: int = 50) -> dict:
    return {"tasks": get_activity_store().recent_tasks(limit)}
