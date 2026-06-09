"""WhatsApp Agent (LangGraph tool-calling loop).

Sends, schedules, and broadcasts WhatsApp messages via Twilio by calling the
messaging tools one at a time. Same loop shape as the other specialists. All
messaging tools are approval-gated.
"""

import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.core.llm import LLMClient
from app.core.logging import get_logger
from app.services.whatsapp_service import WhatsAppService
from app.tools.builtin import make_default_registry
from app.tools.pipeline import ToolPipeline
from app.tools.registry import ToolRegistry, render_tool_catalog
from app.tools.schemas import ToolContext
from app.tools.whatsapp_tools import make_whatsapp_tools

log = get_logger(__name__)


class WhatsAppAgentState(TypedDict, total=False):
    user_id: str
    instruction: str
    approved: bool
    history: list[dict]
    next: dict
    calls: list[dict]
    iters: int
    answer: str


def _system(tools_catalog: str, max_iters: int) -> str:
    return f"""You are a messaging assistant that sends WhatsApp messages via \
Twilio. Fulfil the request by calling messaging tools one at a time.

Tools (use the exact tool name):
{tools_catalog}

Reply with a single JSON object, one of:
  {{"action": "call", "tool": "messaging.<op>", "args": {{...}}}}
  {{"action": "finish", "answer": "<short summary for the user>"}}

Rules:
- Sending, scheduling, and broadcasting all require approval; if held, say so.
- For scheduling, "send_at" must be an ISO 8601 time in the future.
- One tool per turn; finish within {max_iters} steps."""


def build_whatsapp_agent_graph(
    registry: ToolRegistry, pipeline: ToolPipeline, llm: LLMClient, max_iters: int
):
    tools = registry.by_capability("messaging")
    catalog = render_tool_catalog(tools)

    async def think_node(state: WhatsAppAgentState) -> dict:
        user = json.dumps({"instruction": state["instruction"],
                           "history": state.get("history", [])})
        try:
            decision = await llm.complete_json(_system(catalog, max_iters), user)
        except Exception as exc:  # noqa: BLE001
            log.warning("whatsapp_agent.think_failed", error=str(exc))
            decision = {"action": "finish", "answer": "I could not plan the messaging task."}
        return {"next": decision, "iters": state.get("iters", 0) + 1}

    async def act_node(state: WhatsAppAgentState) -> dict:
        decision = state.get("next", {})
        tool = registry.get(decision.get("tool", ""))
        args = decision.get("args", {}) or {}
        history = list(state.get("history", []))
        calls = list(state.get("calls", []))

        if tool is None or tool.capability != "messaging":
            observation = {"error": f"unknown messaging tool: {decision.get('tool')}"}
            history.append({"decision": decision, "observation": observation})
            return {"history": history}

        ctx = ToolContext(user_id=state["user_id"], approved=state.get("approved", False))
        result = await pipeline.execute(tool, args, ctx)
        observation = {"status": result.status.value, "ok": result.ok,
                       "data": result.data,
                       "error": result.error.model_dump() if result.error else None}
        history.append({"decision": decision, "observation": observation})
        calls.append({"tool": tool.name, "args": args, **observation})
        return {"history": history, "calls": calls}

    async def finish_node(state: WhatsAppAgentState) -> dict:
        return {"answer": state.get("next", {}).get("answer") or "Done."}

    def route(state: WhatsAppAgentState) -> str:
        if state.get("iters", 0) >= max_iters:
            return "finish"
        return "finish" if state.get("next", {}).get("action") == "finish" else "act"

    g = StateGraph(WhatsAppAgentState)
    g.add_node("think", think_node)
    g.add_node("act", act_node)
    g.add_node("finish", finish_node)

    g.add_edge(START, "think")
    g.add_conditional_edges("think", route, {"act": "act", "finish": "finish"})
    g.add_edge("act", "think")
    g.add_edge("finish", END)

    return g.compile()


class WhatsAppAgent:
    def __init__(
        self,
        registry: ToolRegistry | None = None,
        pipeline: ToolPipeline | None = None,
        llm: LLMClient | None = None,
        max_iters: int | None = None,
    ) -> None:
        self.registry = registry or make_default_registry()
        self.pipeline = pipeline or ToolPipeline()
        self.llm = llm or LLMClient()
        self.max_iters = max_iters or get_settings().whatsapp_agent_max_iters
        self.graph = build_whatsapp_agent_graph(
            self.registry, self.pipeline, self.llm, self.max_iters)

    async def arun(self, user_id: str, instruction: str, approved: bool = False) -> dict:
        out = await self.graph.ainvoke({
            "user_id": user_id, "instruction": instruction,
            "approved": approved, "history": [], "calls": [], "iters": 0,
        })
        return {"answer": out.get("answer"), "calls": out.get("calls", [])}


def get_whatsapp_agent() -> WhatsAppAgent:
    return WhatsAppAgent()


def whatsapp_registry(service: WhatsAppService) -> ToolRegistry:
    reg = ToolRegistry()
    for tool in make_whatsapp_tools(service):
        reg.register(tool)
    return reg
