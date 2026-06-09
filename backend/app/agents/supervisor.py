"""Supervisor Agent (LangGraph orchestration).

The top of the stack. It recalls memory, classifies the request, and routes:

    START -> recall -> classify ─(chat)──▶ chat ───────────────▶ END
                                ─(single)▶ single ─▶ synthesize ─▶ END
                                ─(plan)──▶ plan ─(ready)─▶ execute ┐
                                                └(invalid)─────────┴▶ synthesize ▶ END

- chat: a direct LLM answer, no tools (the cheapest path).
- single: one capability, executed as a one-step plan through the same executor.
- plan: hand the goal to the Planner Agent (Phase 3); if the plan validates,
  the executor walks it; either way synthesis explains the outcome.

Tool calls flow through the pipeline, so risk gating and audit apply uniformly.
All collaborators are injected, so the whole graph runs in tests with canned
models and an in-memory memory agent, and in production with the real ones.
"""

from collections.abc import Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from app.agents.classifier import IntentClassifier
from app.agents.executor import PlanExecutor
from app.agents.state import SupervisorState
from app.core.llm import LLMClient
from app.core.logging import get_logger
from app.planner.agent import PlannerAgent
from app.planner.schemas import Plan, PlanStatus, PlanStep
from app.tools.pipeline import ToolPipeline
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolContext
from app.tools.selector import ToolSelector

log = get_logger(__name__)

MemoryRetriever = Callable[[str, str], Awaitable[str]]  # (user_id, query) -> block

_CHAT_SYSTEM = "You are a helpful personal assistant. Answer the user concisely. " \
    "Use the remembered context if relevant."
_SYNTH_SYSTEM = (
    "You are a personal assistant composing the final reply. You ran some tools; "
    "summarize the outcome for the user concisely and honestly. If a tool result "
    "is a stub or was held for approval, say so plainly rather than pretending it "
    "succeeded."
)


def build_supervisor_graph(
    classifier: IntentClassifier,
    planner: PlannerAgent,
    executor: PlanExecutor,
    llm: LLMClient,
    memory_agent,
    memory_retriever: MemoryRetriever | None,
):
    def _ctx(state: SupervisorState) -> ToolContext:
        return ToolContext(
            user_id=state["user_id"],
            thread_id=state.get("thread_id"),
            approved=state.get("approved", False),
            deps={"memory_agent": memory_agent},
        )

    async def recall_node(state: SupervisorState) -> dict:
        if memory_retriever is None:
            return {"memory_block": ""}
        try:
            block = await memory_retriever(state["user_id"], state["message"])
        except Exception as exc:  # noqa: BLE001
            log.warning("supervisor.recall_failed", error=str(exc))
            block = ""
        return {"memory_block": block}

    async def classify_node(state: SupervisorState) -> dict:
        result = await classifier.classify(state["message"], state.get("memory_block", ""))
        return {"route": result.route, "capability": result.capability}

    async def chat_node(state: SupervisorState) -> dict:
        user = state["message"]
        if state.get("memory_block"):
            user = f"{state['memory_block']}\n\nUser: {state['message']}"
        answer = await _safe_text(llm, _CHAT_SYSTEM, user, fallback=state["message"])
        return {"answer": answer}

    async def single_node(state: SupervisorState) -> dict:
        # Execute the one capability as a single-step plan through the executor.
        step = PlanStep(
            id="s1", description=state["message"],
            capability=state.get("capability") or "memory",
            inputs={"query": state["message"]},
        )
        plan = Plan(goal=state["message"], steps=[step],
                    order=["s1"], status=PlanStatus.READY)
        results = await executor.run(plan, _ctx(state))
        return {"plan": plan.model_dump(mode="json"),
                "results": [r.model_dump() for r in results]}

    async def plan_node(state: SupervisorState) -> dict:
        plan = await planner.aplan(state["message"], state.get("memory_block", ""))
        return {"plan": plan.model_dump(mode="json")}

    async def execute_node(state: SupervisorState) -> dict:
        plan = Plan(**state["plan"])
        results = await executor.run(plan, _ctx(state))
        return {"results": [r.model_dump() for r in results]}

    async def synthesize_node(state: SupervisorState) -> dict:
        import json

        payload = json.dumps({
            "message": state["message"],
            "memory": state.get("memory_block", ""),
            "results": state.get("results", []),
            "plan_errors": (state.get("plan") or {}).get("errors", []),
        })
        answer = await _safe_text(
            llm, _SYNTH_SYSTEM, payload, fallback=_fallback_answer(state))
        return {"answer": answer}

    def route_after_classify(state: SupervisorState) -> str:
        return state.get("route", "plan")

    def route_after_plan(state: SupervisorState) -> str:
        status = (state.get("plan") or {}).get("status")
        return "ready" if status == PlanStatus.READY.value else "invalid"

    g = StateGraph(SupervisorState)
    g.add_node("recall", recall_node)
    g.add_node("classify", classify_node)
    g.add_node("chat", chat_node)
    g.add_node("single", single_node)
    g.add_node("plan", plan_node)
    g.add_node("execute", execute_node)
    g.add_node("synthesize", synthesize_node)

    g.add_edge(START, "recall")
    g.add_edge("recall", "classify")
    g.add_conditional_edges(
        "classify", route_after_classify,
        {"chat": "chat", "single": "single", "plan": "plan"})
    g.add_edge("chat", END)
    g.add_edge("single", "synthesize")
    g.add_conditional_edges(
        "plan", route_after_plan, {"ready": "execute", "invalid": "synthesize"})
    g.add_edge("execute", "synthesize")
    g.add_edge("synthesize", END)

    return g.compile()


async def _safe_text(llm: LLMClient, system: str, user: str, fallback: str) -> str:
    try:
        text = await llm.complete_text(system, user)
        return text or fallback
    except Exception as exc:  # noqa: BLE001
        log.warning("supervisor.llm_text_failed", error=str(exc))
        return fallback


def _fallback_answer(state: SupervisorState) -> str:
    results = state.get("results", [])
    if not results:
        return "I could not produce a result."
    lines = [f"- {r.get('step_id')}: {r.get('status')}" for r in results]
    return "Here is what happened:\n" + "\n".join(lines)


class SupervisorAgent:
    def __init__(
        self,
        llm: LLMClient | None = None,
        registry: ToolRegistry | None = None,
        planner: PlannerAgent | None = None,
        memory_agent=None,
        classifier: IntentClassifier | None = None,
        memory_retriever: MemoryRetriever | None = None,
    ) -> None:
        from app.tools.builtin import make_default_registry

        self.llm = llm or LLMClient()
        self.registry = registry or make_default_registry()
        self.memory_agent = memory_agent
        self.planner = planner or PlannerAgent(llm=self.llm)
        capabilities = sorted({t.capability for t in self.registry.all()})
        self.classifier = classifier or IntentClassifier(capabilities, self.llm)
        selector = ToolSelector(self.registry, self.llm)
        self.executor = PlanExecutor(selector, ToolPipeline())
        self.graph = build_supervisor_graph(
            self.classifier, self.planner, self.executor, self.llm,
            self.memory_agent, memory_retriever)

    async def arun(
        self, user_id: str, message: str,
        thread_id: str | None = None, approved: bool = False,
    ) -> dict:
        return await self.graph.ainvoke({
            "user_id": user_id, "message": message,
            "thread_id": thread_id, "approved": approved,
        })


def get_supervisor_agent() -> SupervisorAgent:
    """Production wiring: real LLM, planner, tool registry, and memory agent."""
    from app.memory.agent import MemoryAgent

    memory_agent = MemoryAgent()

    async def retriever(user_id: str, query: str) -> str:
        out = await memory_agent.aretrieve(user_id, query)
        return out.get("memory_block", "")

    return SupervisorAgent(memory_agent=memory_agent, memory_retriever=retriever)
