"""Built-in tools.

Phase 4 ships ONE real tool, memory.retrieve, wired to the Phase 2 Memory
Agent. Every other capability is registered as a clearly labeled STUB so the
supervisor and executor run end to end and every pipeline branch is exercised
(a read that succeeds, a write that succeeds, and a destructive action that the
risk gate holds for approval). The real integrations replace these stubs in
later phases without touching the orchestration.
"""

from pydantic import BaseModel, ConfigDict

from app.tools.registry import ToolRegistry
from app.tools.schemas import RiskClass, ToolContext, ToolSpec


class _Loose(BaseModel):
    """Permissive args: accept whatever the planner emits (including resolved
    "$step.output" references) without rejecting stub calls."""

    model_config = ConfigDict(extra="allow")


class MemoryRetrieveArgs(BaseModel):
    query: str
    action: str = "retrieve"


async def _memory_retrieve(args: MemoryRetrieveArgs, ctx: ToolContext) -> dict:
    agent = ctx.deps.get("memory_agent")
    if agent is None:
        return {"memory_block": "", "memories": [], "note": "no memory agent wired"}
    out = await agent.aretrieve(ctx.user_id, args.query)
    return {
        "memory_block": out.get("memory_block", ""),
        "memories": out.get("retrieved", []),
    }


def _make_stub(name: str, capability: str, description: str,
               risk: RiskClass, requires_approval: bool) -> ToolSpec:
    async def handler(args: _Loose, ctx: ToolContext) -> dict:
        return {
            "stub": True,
            "tool": name,
            "note": f"{name} is a stub; real implementation arrives in a later phase",
            "echo": args.model_dump(),
        }

    return ToolSpec(
        name=name, capability=capability, description=description,
        args_schema=_Loose, handler=handler,
        risk_class=risk, requires_approval=requires_approval,
    )


def make_default_registry() -> ToolRegistry:
    from app.services.file_service import FileService
    from app.tools.file_tools import make_file_tools

    reg = ToolRegistry()

    # Real
    reg.register(ToolSpec(
        name="memory.retrieve", capability="memory",
        description="Retrieve facts the assistant remembers about the user.",
        args_schema=MemoryRetrieveArgs, handler=_memory_retrieve,
        risk_class=RiskClass.READ, requires_approval=False,
    ))

    # Real file tools (Phase 5): create / read / delete / rename / search.
    for tool in make_file_tools(FileService()):
        reg.register(tool)

    # Real code tools (Phase 6): generate / review / debug / execute.
    from app.core.llm import LLMClient
    from app.services.code_sandbox import get_sandbox
    from app.tools.code_tools import make_code_tools

    for tool in make_code_tools(get_sandbox(), LLMClient()):
        reg.register(tool)

    # Real browser tools (Phase 7): open / search / extract / fill.
    from app.services.browser_service import PlaywrightBrowserService
    from app.tools.browser_tools import make_browser_tools

    for tool in make_browser_tools(PlaywrightBrowserService()):
        reg.register(tool)

    # Real Gmail tools (Phase 8): read_inbox / search / draft_reply / send.
    from app.services.gmail_service import GmailApiService
    from app.tools.gmail_tools import make_gmail_tools

    for tool in make_gmail_tools(GmailApiService()):
        reg.register(tool)

    # Real Spotify tools (Phase 9): search / play / pause / skip / create_playlist.
    from app.services.spotify_service import SpotifyApiService
    from app.tools.spotify_tools import make_spotify_tools

    for tool in make_spotify_tools(SpotifyApiService()):
        reg.register(tool)

    # Real WhatsApp tools (Phase 10): send / schedule / broadcast.
    from app.services.whatsapp_service import TwilioWhatsAppService
    from app.tools.whatsapp_tools import make_whatsapp_tools

    for tool in make_whatsapp_tools(TwilioWhatsAppService()):
        reg.register(tool)

    # Stubs (replaced as later phases land their integrations).
    reg.register(_make_stub("calendar.create", "calendar",
                            "Create a calendar event.", RiskClass.WRITE, False))

    return reg
