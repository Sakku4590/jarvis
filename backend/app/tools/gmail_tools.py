"""Gmail tools.

Four tools under the "email" capability, replacing the Phase 4 stubs:
  - email.read_inbox / email.search: READ.
  - email.draft_reply: creates a draft (does not send), WRITE, not gated.
  - email.send: sends mail, DESTRUCTIVE and approval-gated.

Each handler uses ctx.user_id so the per-user Gmail credentials are loaded by
the service.
"""

from pydantic import BaseModel

from app.services.gmail_service import GmailService
from app.tools.schemas import RiskClass, ToolContext, ToolSpec


class ReadInboxArgs(BaseModel):
    max_results: int = 20
    action: str = "read_inbox"


class SearchArgs(BaseModel):
    query: str
    max_results: int = 20
    action: str = "search"


class SendArgs(BaseModel):
    to: str
    subject: str
    body: str
    action: str = "send"


class DraftReplyArgs(BaseModel):
    message_id: str
    body: str
    action: str = "draft_reply"


def make_gmail_tools(service: GmailService) -> list[ToolSpec]:
    async def read_inbox(args: ReadInboxArgs, ctx: ToolContext) -> dict:
        return await service.list_inbox(ctx.user_id, args.max_results)

    async def search(args: SearchArgs, ctx: ToolContext) -> dict:
        return await service.search(ctx.user_id, args.query, args.max_results)

    async def send(args: SendArgs, ctx: ToolContext) -> dict:
        return await service.send(ctx.user_id, args.to, args.subject, args.body)

    async def draft_reply(args: DraftReplyArgs, ctx: ToolContext) -> dict:
        return await service.draft_reply(ctx.user_id, args.message_id, args.body)

    return [
        ToolSpec(name="email.read_inbox", capability="email",
                 description="List recent inbox messages (sender, subject, snippet).",
                 args_schema=ReadInboxArgs, handler=read_inbox,
                 risk_class=RiskClass.READ, requires_approval=False),
        ToolSpec(name="email.search", capability="email",
                 description="Search email with a Gmail query (e.g. 'from:bob is:unread').",
                 args_schema=SearchArgs, handler=search,
                 risk_class=RiskClass.READ, requires_approval=False),
        ToolSpec(name="email.draft_reply", capability="email",
                 description="Create a draft reply to a message. Does not send.",
                 args_schema=DraftReplyArgs, handler=draft_reply,
                 risk_class=RiskClass.WRITE, requires_approval=False),
        ToolSpec(name="email.send", capability="email",
                 description="Send an email. Irreversible and externally visible.",
                 args_schema=SendArgs, handler=send,
                 risk_class=RiskClass.DESTRUCTIVE, requires_approval=True),
    ]
