"""WhatsApp API.

  GET  /integrations/whatsapp/status  -> { configured }
  POST /messaging/task                -> run the WhatsApp agent

Twilio uses account-level credentials from config, so there is no OAuth flow.
"""

from functools import lru_cache

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.whatsapp_agent import WhatsAppAgent, get_whatsapp_agent
from app.core.config import get_settings

router = APIRouter(tags=["whatsapp"])


@lru_cache
def _agent() -> WhatsAppAgent:
    return get_whatsapp_agent()


@router.get("/integrations/whatsapp/status")
async def whatsapp_status() -> dict:
    s = get_settings()
    return {
        "configured": bool(s.twilio_account_sid and s.twilio_auth_token
                           and s.twilio_whatsapp_from),
        "scheduling_enabled": bool(s.twilio_messaging_service_sid),
    }


class MessagingTaskRequest(BaseModel):
    user_id: str
    instruction: str
    approved: bool = False


@router.post("/messaging/task")
async def messaging_task(req: MessagingTaskRequest) -> dict:
    return await _agent().arun(req.user_id, req.instruction, req.approved)
