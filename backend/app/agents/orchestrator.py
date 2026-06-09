"""Orchestrator (Phase 11): all agents in one LangGraph workflow.

This is the capstone graph. It recalls memory, classifies the request, and routes
into chat, a single specialist, or a planned multi-step run. The key difference
from the Phase 4 supervisor is delegation: instead of calling one tool per plan
step, the executor hands each step to the SPECIALIST AGENT for that capability
(File, Coding, Browser, Email, Spotify, WhatsApp), each of which is itself a
LangGraph tool-calling loop. So this is a graph of graphs.

    START -> recall -> classify ─(chat)──▶ chat ───────────────▶ END
                                ─(single)▶ single ─▶ synthesize ─▶ END
                                ─(plan)──▶ plan ─(ready)─▶ execute ┐
                                                └(invalid)─────────┴▶ synthesize ▶ END

Capabilities with no specialist agent (calendar, memory) fall back to direct
tool dispatch through the same pipeline, so the approval gate and audit still
apply everywhere. `approved` propagates into every agent and tool call.
"""

import json
from collections.abc import Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from app.agents.agent_registry import AgentRegistry
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

MemoryRetriever = Callable[[str, str], Awaitable[str]]

_CHAT_SYSTEM = ("You are a helpful personal assistant. Answer concisely, using "
               "the remembered context if relevant.")
_SYNTH_SYSTEM = ("You are the assistant composing the final reply. Specialist "
                 "agents handled the steps; summarize the outcome concisely and "
                 "honestly. If a step was held for approval or failed, say so.")


def _resolve_inputs(inputs: dict, outputs: dict) -> dict:
    out = {}
    for k, v in inputs.items():
        if isinstance(v, str) and v.startswith("$"):
            out[k] = outputs.get(v[1:].split(".", 1)[0])
        else:
            out[k] = v
    return out


def _compose_instruction(step: PlanStep, outputs: dict) -> str:
    inst = step.description
    resolved = _resolve_inputs(step.inputs, outputs)
    if resolved:
        inst += "\nInputs: " + json.dumps(resolved, default=str)
    return inst


def _derive_status(calls: list[dict]) -> str:
    statuses = {c.get("status") for c in calls}
    if "pending_approval" in statuses:
        return "pending_approval"
    if statuses & {"error", "invalid_args", "not_permitted"}:
        return "error"
    return "success"


def build_orchestrator_graph(
    classifier: IntentClassifier,
    planner: PlannerAgent,
    agents: AgentRegistry,
    fallback: PlanExecutor,
    llm: LLMClient,
    memory_retriever: MemoryRetriever | None,
):
    async def recall_node(state: SupervisorState) -> dict:
        if memory_retriever is None:
            return {"memory_block": ""}
        try:
            return {"memory_block": await memory_retriever(state["user_id"], state["message"])}
        except Exception as exc:  # noqa: BLE001
            log.warning("orchestrator.recall_failed", error=str(exc))
            return {"memory_block": ""}

    async def classify_node(state: SupervisorState) -> dict:
        result = await classifier.classify(state["message"], state.get("memory_block", ""))
        return {"route": result.route, "capability": result.capability}

    async def chat_node(state: SupervisorState) -> dict:
        user = state["message"]
        if state.get("memory_block"):
            user = f"{state['memory_block']}\n\nUser: {state['message']}"
        return {"answer": await _safe_text(llm, _CHAT_SYSTEM, user, state["message"])}

    async def single_node(state: SupervisorState) -> dict:
        cap = state.get("capability") or ""
        agent = agents.get(cap)
        if agent is not None:
            res = await agent.arun(state["user_id"], state["message"],
                                   state.get("approved", False))
            return {"results": [{"step_id": "single", "capability": cap,
                                 "delegate": "agent", "status": _derive_status(res.get("calls", [])),
                                 "answer": res.get("answer"), "calls": res.get("calls", [])}]}
        # Fallback: run as a one-step tool plan.
        step = PlanStep(id="s1", description=state["message"], capability=cap or "memory",
                        inputs={"query": state["message"]})
        plan = Plan(goal=state["message"], steps=[step], order=["s1"], status=PlanStatus.READY)
        results = await fallback.run(plan, _ctx(state))
        return {"results": [r.model_dump() for r in results]}

    async def plan_node(state: SupervisorState) -> dict:
        plan = await planner.aplan(state["message"], state.get("memory_block", ""))
        return {"plan": plan.model_dump(mode="json")}

    async def execute_node(state: SupervisorState) -> dict:
        plan = Plan(**state["plan"])
        results = await _execute_with_agents(
            plan, state["user_id"], state.get("approved", False), agents, fallback)
        return {"results": results}

    async def synthesize_node(state: SupervisorState) -> dict:
        payload = json.dumps({
            "message": state["message"],
            "memory": state.get("memory_block", ""),
            "results": state.get("results", []),
            "plan_errors": (state.get("plan") or {}).get("errors", []),
        }, default=str)
        return {"answer": await _safe_text(llm, _SYNTH_SYSTEM, payload,
                                           _fallback_answer(state))}

    def _ctx(state: SupervisorState) -> ToolContext:
        return ToolContext(user_id=state["user_id"], approved=state.get("approved", False))

    def route_after_classify(state: SupervisorState) -> str:
        return state.get("route", "plan")

    def route_after_plan(state: SupervisorState) -> str:
        return "ready" if (state.get("plan") or {}).get("status") == PlanStatus.READY.value \
            else "invalid"

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
    g.add_conditional_edges("classify", route_after_classify,
                            {"chat": "chat", "single": "single", "plan": "plan"})
    g.add_edge("chat", END)
    g.add_edge("single", "synthesize")
    g.add_conditional_edges("plan", route_after_plan,
                            {"ready": "execute", "invalid": "synthesize"})
    g.add_edge("execute", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()


async def _execute_with_agents(plan: Plan, user_id: str, approved: bool,
                               agents: AgentRegistry, fallback: PlanExecutor) -> list[dict]:
    outputs: dict = {}
    blocked: set[str] = set()
    results: list[dict] = []

    for step_id in plan.order:
        step = plan.step(step_id)
        if step is None:
            continue
        if any(d in blocked for d in step.depends_on):
            blocked.add(step_id)
            results.append({"step_id": step_id, "capability": step.capability,
                            "status": "skipped", "error": {"code": "dependency_unmet"}})
            continue

        agent = agents.get(step.capability)
        if agent is not None:
            instruction = _compose_instruction(step, outputs)
            res = await agent.arun(user_id, instruction, approved)
            status = _derive_status(res.get("calls", []))
            outputs[step_id] = res.get("answer")
            results.append({"step_id": step_id, "capability": step.capability,
                            "delegate": "agent", "status": status,
                            "answer": res.get("answer"), "calls": res.get("calls", [])})
            if status != "success":
                blocked.add(step_id)
        else:
            resolved = _resolve_inputs(step.inputs, outputs)
            one = Plan(goal=plan.goal, status=PlanStatus.READY, order=[step_id],
                       steps=[step.model_copy(update={"inputs": resolved, "depends_on": []})])
            sr = (await fallback.run(one, ToolContext(user_id=user_id, approved=approved)))[0]
            outputs[step_id] = sr.data
            results.append({"step_id": step_id, "capability": step.capability,
                            "delegate": "tool", "status": sr.status, "ok": sr.ok,
                            "data": sr.data, "error": sr.error})
            if not sr.ok:
                blocked.add(step_id)

    log.info("orchestrator.execute", steps=len(results), blocked=len(blocked))
    return results


async def _safe_text(llm: LLMClient, system: str, user: str, fallback: str) -> str:
    try:
        return (await llm.complete_text(system, user)) or fallback
    except Exception as exc:  # noqa: BLE001
        log.warning("orchestrator.text_failed", error=str(exc))
        return fallback


def _fallback_answer(state: SupervisorState) -> str:
    results = state.get("results", [])
    if not results:
        return "I could not produce a result."
    return "Here is what happened:\n" + "\n".join(
        f"- {r.get('step_id')} ({r.get('capability')}): {r.get('status')}" for r in results)


class Orchestrator:
    def __init__(
        self,
        llm: LLMClient | None = None,
        agents: AgentRegistry | None = None,
        planner: PlannerAgent | None = None,
        memory_retriever: MemoryRetriever | None = None,
        fallback_registry: ToolRegistry | None = None,
    ) -> None:
        from app.tools.builtin import make_default_registry

        self.llm = llm or LLMClient()
        self.agents = agents or _default_agents()
        self.planner = planner or PlannerAgent(llm=self.llm)
        registry = fallback_registry or make_default_registry()
        self.fallback = PlanExecutor(ToolSelector(registry, self.llm), ToolPipeline())
        caps = sorted(set(self.agents.capabilities()) |
                      {t.capability for t in registry.all()})
        self.classifier = IntentClassifier(caps, self.llm)
        self.memory_retriever = memory_retriever
        self.graph = build_orchestrator_graph(
            self.classifier, self.planner, self.agents, self.fallback,
            self.llm, self.memory_retriever)

    async def arun(self, user_id: str, message: str, approved: bool = False) -> dict:
        out = await self.graph.ainvoke({
            "user_id": user_id, "message": message, "approved": approved})
        return {"route": out.get("route"), "answer": out.get("answer"),
                "plan": out.get("plan"), "results": out.get("results", [])}


def _default_agents() -> AgentRegistry:
    from app.agents.browser_agent import BrowserAgent
    from app.agents.coding_agent import CodingAgent
    from app.agents.file_agent import FileAgent
    from app.agents.gmail_agent import GmailAgent
    from app.agents.spotify_agent import SpotifyAgent
    from app.agents.whatsapp_agent import WhatsAppAgent

    return AgentRegistry({
        "file": FileAgent(),
        "code": CodingAgent(),
        "browser": BrowserAgent(),
        "email": GmailAgent(),
        "music": SpotifyAgent(),
        "messaging": WhatsAppAgent(),
    })


def get_orchestrator() -> Orchestrator:
    from app.memory.agent import MemoryAgent

    memory_agent = MemoryAgent()

    async def retriever(user_id: str, query: str) -> str:
        out = await memory_agent.aretrieve(user_id, query)
        return out.get("memory_block", "")

    return Orchestrator(memory_retriever=retriever)
