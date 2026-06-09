"""Coding Agent (LangGraph tool-calling loop).

Fulfils a coding task by calling the code tools one at a time: generate, review,
debug, and execute. The loop mirrors the File Agent:

    START -> think ─(call)─▶ act ─▶ think
                   └(finish)────────────▶ finish -> END

A typical flow is generate -> execute -> (on failure) debug -> execute again.
Every call goes through the ToolPipeline, so code.execute is held by the risk
gate unless the request is approved, and the sandbox limits apply to every run.
Provider-agnostic JSON tool-calling, same as the File Agent.
"""

import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.core.llm import LLMClient
from app.core.logging import get_logger
from app.services.code_sandbox import CodeSandbox, get_sandbox
from app.tools.builtin import make_default_registry
from app.tools.code_tools import make_code_tools
from app.tools.pipeline import ToolPipeline
from app.tools.registry import ToolRegistry, render_tool_catalog
from app.tools.schemas import ToolContext

log = get_logger(__name__)


class CodingAgentState(TypedDict, total=False):
    user_id: str
    instruction: str
    approved: bool
    history: list[dict]
    next: dict
    calls: list[dict]
    iters: int
    answer: str


def _system(tools_catalog: str, max_iters: int) -> str:
    return f"""You are a coding agent. Fulfil the user's request by calling code \
tools one at a time.

Tools (use the exact tool name):
{tools_catalog}

Reply with a single JSON object, one of:
  {{"action": "call", "tool": "code.<op>", "args": {{...}}}}
  {{"action": "finish", "answer": "<short summary, include final code or result>"}}

Rules:
- Call one tool per turn; after each result decide the next step.
- To run code you must pass the full source in args.code. Executing requires \
approval; if execution is held, report that and still return the code.
- If execution fails, use code.debug on the code and error, then try again.
- Finish as soon as the task is satisfied (within {max_iters} steps)."""


def build_coding_agent_graph(
    registry: ToolRegistry, pipeline: ToolPipeline, llm: LLMClient, max_iters: int
):
    tools = registry.by_capability("code")
    catalog = render_tool_catalog(tools)

    async def think_node(state: CodingAgentState) -> dict:
        user = json.dumps({"instruction": state["instruction"],
                           "history": state.get("history", [])})
        try:
            decision = await llm.complete_json(_system(catalog, max_iters), user)
        except Exception as exc:  # noqa: BLE001
            log.warning("coding_agent.think_failed", error=str(exc))
            decision = {"action": "finish", "answer": "I could not plan the coding task."}
        return {"next": decision, "iters": state.get("iters", 0) + 1}

    async def act_node(state: CodingAgentState) -> dict:
        decision = state.get("next", {})
        tool = registry.get(decision.get("tool", ""))
        args = decision.get("args", {}) or {}
        history = list(state.get("history", []))
        calls = list(state.get("calls", []))

        if tool is None or tool.capability != "code":
            observation = {"error": f"unknown code tool: {decision.get('tool')}"}
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

    async def finish_node(state: CodingAgentState) -> dict:
        return {"answer": state.get("next", {}).get("answer") or "Done."}

    def route(state: CodingAgentState) -> str:
        if state.get("iters", 0) >= max_iters:
            return "finish"
        return "finish" if state.get("next", {}).get("action") == "finish" else "act"

    g = StateGraph(CodingAgentState)
    g.add_node("think", think_node)
    g.add_node("act", act_node)
    g.add_node("finish", finish_node)

    g.add_edge(START, "think")
    g.add_conditional_edges("think", route, {"act": "act", "finish": "finish"})
    g.add_edge("act", "think")
    g.add_edge("finish", END)

    return g.compile()


class CodingAgent:
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
        self.max_iters = max_iters or get_settings().coding_agent_max_iters
        self.graph = build_coding_agent_graph(
            self.registry, self.pipeline, self.llm, self.max_iters)

    async def arun(self, user_id: str, instruction: str, approved: bool = False) -> dict:
        out = await self.graph.ainvoke({
            "user_id": user_id, "instruction": instruction,
            "approved": approved, "history": [], "calls": [], "iters": 0,
        })
        return {"answer": out.get("answer"), "calls": out.get("calls", [])}


def get_coding_agent() -> CodingAgent:
    return CodingAgent()


def code_registry(sandbox: CodeSandbox, llm: LLMClient) -> ToolRegistry:
    """A registry of only the code tools, for isolated testing."""
    reg = ToolRegistry()
    for tool in make_code_tools(sandbox, llm):
        reg.register(tool)
    return reg
