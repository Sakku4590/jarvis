"""WhatsApp tools (capability "messaging").

Sending, scheduling, and broadcasting messages are all externally visible
actions, so all three are DESTRUCTIVE and approval-gated.
"""

from pydantic import BaseModel

from app.services.whatsapp_service import WhatsAppService
from app.tools.schemas import RiskClass, ToolContext, ToolSpec


class SendArgs(BaseModel):
    to: str
    body: str
    action: str = "send"


class ScheduleArgs(BaseModel):
    to: str
    body: str
    send_at: str  # ISO 8601, in the future
    action: str = "schedule"


class BroadcastArgs(BaseModel):
    recipients: list[str]
    body: str
    action: str = "broadcast"


def make_whatsapp_tools(service: WhatsAppService) -> list[ToolSpec]:
    async def send(args: SendArgs, ctx: ToolContext) -> dict:
        return await service.send(args.to, args.body)

    async def schedule(args: ScheduleArgs, ctx: ToolContext) -> dict:
        return await service.schedule(args.to, args.body, args.send_at)

    async def broadcast(args: BroadcastArgs, ctx: ToolContext) -> dict:
        return await service.broadcast(args.recipients, args.body)

    return [
        ToolSpec(name="messaging.send", capability="messaging",
                 description="Send a WhatsApp message to a number.",
                 args_schema=SendArgs, handler=send,
                 risk_class=RiskClass.DESTRUCTIVE, requires_approval=True),
        ToolSpec(name="messaging.schedule", capability="messaging",
                 description="Schedule a WhatsApp message for a future ISO time.",
                 args_schema=ScheduleArgs, handler=schedule,
                 risk_class=RiskClass.DESTRUCTIVE, requires_approval=True),
        ToolSpec(name="messaging.broadcast", capability="messaging",
                 description="Send a WhatsApp message to several recipients.",
                 args_schema=BroadcastArgs, handler=broadcast,
                 risk_class=RiskClass.DESTRUCTIVE, requires_approval=True),
    ]
