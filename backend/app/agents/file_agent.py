"""File Agent (LangGraph tool-calling loop).

A ReAct-style agent that fulfils a natural-language file instruction by calling
the file tools. The loop is think -> act -> think until the model finishes or the
iteration cap is hit:

    START -> think ─(call)─▶ act ─▶ think
                   └(finish)────────────▶ finish -> END

The model emits one decision at a time as JSON (call a tool, or finish with an
answer). Every tool call goes through the ToolPipeline, so the workspace
sandbox, the risk gate (delete needs approval), and audit all apply here exactly
as they do on the supervisor path. Provider-agnostic: it uses our JSON LLM
client rather than a vendor-specific function-calling format.
"""

import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.core.llm import LLMClient
from app.core.logging import get_logger
from app.services.file_service import FileService
from app.tools.builtin import make_default_registry
from app.tools.file_tools import make_file_tools
from app.tools.pipeline import ToolPipeline
from app.tools.registry import ToolRegistry, render_tool_catalog
from app.tools.schemas import ToolContext

log = get_logger(__name__)


class FileAgentState(TypedDict, total=False):
    user_id: str
    instruction: str
    approved: bool
    history: list[dict]   # [{decision, observation}]
    next: dict            # latest model decision
    calls: list[dict]     # [{tool, args, status, ok, data, error}]
    iters: int
    answer: str


def _system(tools_catalog: str, max_iters: int) -> str:
    return f"""You are a file management agent operating inside a sandboxed \
workspace. Fulfil the user's instruction by calling file tools one at a time.

Tools (use the exact tool name):
{tools_catalog}

Reply with a single JSON object, one of:
  {{"action": "call", "tool": "file.<op>", "args": {{...}}}}
  {{"action": "finish", "answer": "<short summary for the user>"}}

Rules:
- Call one tool per turn. After each call you will see its result, then decide \
the next step.
- Paths are relative to the workspace. Never use absolute paths or "..".
- Deleting requires approval; if a delete is held, report that in your answer.
- Finish as soon as the instruction is satisfied (within {max_iters} steps)."""


def build_file_agent_graph(
    registry: ToolRegistry, pipeline: ToolPipeline, llm: LLMClient, max_iters: int
):
    tools = registry.by_capability("file")
    catalog = render_tool_catalog(tools)

    async def think_node(state: FileAgentState) -> dict:
        history = state.get("history", [])
        user = json.dumps({"instruction": state["instruction"], "history": history})
        try:
            decision = await llm.complete_json(_system(catalog, max_iters), user)
        except Exception as exc:  # noqa: BLE001
            log.warning("file_agent.think_failed", error=str(exc))
            decision = {"action": "finish", "answer": "I could not plan the file task."}
        return {"next": decision, "iters": state.get("iters", 0) + 1}

    async def act_node(state: FileAgentState) -> dict:
        decision = state.get("next", {})
        tool = registry.get(decision.get("tool", ""))
        args = decision.get("args", {}) or {}
        history = list(state.get("history", []))
        calls = list(state.get("calls", []))

        if tool is None or tool.capability != "file":
            observation = {"error": f"unknown file tool: {decision.get('tool')}"}
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

    async def finish_node(state: FileAgentState) -> dict:
        answer = state.get("next", {}).get("answer") or "Done."
        return {"answer": answer}

    def route(state: FileAgentState) -> str:
        if state.get("iters", 0) >= max_iters:
            return "finish"
        return "finish" if state.get("next", {}).get("action") == "finish" else "act"

    g = StateGraph(FileAgentState)
    g.add_node("think", think_node)
    g.add_node("act", act_node)
    g.add_node("finish", finish_node)

    g.add_edge(START, "think")
    g.add_conditional_edges("think", route, {"act": "act", "finish": "finish"})
    g.add_edge("act", "think")
    g.add_edge("finish", END)

    return g.compile()


class FileAgent:
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
        self.max_iters = max_iters or get_settings().file_agent_max_iters
        self.graph = build_file_agent_graph(
            self.registry, self.pipeline, self.llm, self.max_iters)

    async def arun(
        self, user_id: str, instruction: str, approved: bool = False
    ) -> dict:
        out = await self.graph.ainvoke({
            "user_id": user_id, "instruction": instruction,
            "approved": approved, "history": [], "calls": [], "iters": 0,
        })
        return {"answer": out.get("answer"), "calls": out.get("calls", [])}


def get_file_agent() -> FileAgent:
    return FileAgent()


def file_registry(service: FileService) -> ToolRegistry:
    """Build a registry containing only the file tools bound to a given service.
    Handy for isolating the workspace in tests."""
    reg = ToolRegistry()
    for tool in make_file_tools(service):
        reg.register(tool)
    return reg
