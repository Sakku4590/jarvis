"""Planner Agent (LangGraph).

A StateGraph with a conditional entry feeding a shared validation node:

    START ─(plan)───▶ decompose ─┐
          └(replan)─▶ replan ────┴─▶ validate ─▶ END

decompose / replan call the LLM to produce draft steps; validate turns them into
a verified, ordered Plan (or marks it invalid with reasons). Dependencies are
injected so the same graph runs with a real LLM in production and a canned one
in tests. The planner is invoked as a step by a supervisor (a later phase), not
a router itself.

Optional memory hook: pass a `retriever` (async callable taking the goal and
returning a context string) to fold Phase 2 memory into planning. Left unset,
the planner runs standalone.
"""

from collections.abc import Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from app.core.llm import LLMClient
from app.core.logging import get_logger
from app.planner.capabilities import CapabilityRegistry, default_registry
from app.planner.decomposer import GoalDecomposer
from app.planner.schemas import Plan, PlanStep
from app.planner.state import PlannerState
from app.planner.validation import validate_plan

log = get_logger(__name__)

Retriever = Callable[[str], Awaitable[str]]


def build_planner_graph(decomposer: GoalDecomposer, registry: CapabilityRegistry):
    """Compile the Planner Agent graph with the given dependencies."""

    async def decompose_node(state: PlannerState) -> dict:
        steps = await decomposer.plan(state["goal"], state.get("context", ""))
        return {"draft_steps": [s.model_dump(mode="json") for s in steps]}

    async def replan_node(state: PlannerState) -> dict:
        current = Plan(**state["current_plan"])
        steps = await decomposer.replan(
            state["goal"], current, state.get("feedback", ""), state.get("context", "")
        )
        return {"draft_steps": [s.model_dump(mode="json") for s in steps]}

    async def validate_node(state: PlannerState) -> dict:
        steps = [PlanStep(**s) for s in state.get("draft_steps", [])]
        plan = Plan(goal=state["goal"], steps=steps)
        plan = validate_plan(plan, registry)
        log.info(
            "planner.validate",
            status=plan.status.value,
            steps=len(plan.steps),
            errors=len(plan.errors),
        )
        return {"plan": plan.model_dump(mode="json")}

    def route(state: PlannerState) -> str:
        return state.get("mode", "plan")

    g = StateGraph(PlannerState)
    g.add_node("decompose", decompose_node)
    g.add_node("replan", replan_node)
    g.add_node("validate", validate_node)

    g.add_conditional_edges(
        START, route, {"plan": "decompose", "replan": "replan"}
    )
    g.add_edge("decompose", "validate")
    g.add_edge("replan", "validate")
    g.add_edge("validate", END)

    return g.compile()


class PlannerAgent:
    """Convenience wrapper over the compiled planner graph."""

    def __init__(
        self,
        llm: LLMClient | None = None,
        registry: CapabilityRegistry | None = None,
        max_steps: int | None = None,
        retriever: Retriever | None = None,
    ) -> None:
        self.registry = registry or default_registry()
        self.decomposer = GoalDecomposer(llm, self.registry, max_steps)
        self.retriever = retriever
        self.graph = build_planner_graph(self.decomposer, self.registry)

    async def aplan(self, goal: str, context: str | None = None) -> Plan:
        if context is None and self.retriever is not None:
            context = await self.retriever(goal)
        out = await self.graph.ainvoke(
            {"mode": "plan", "goal": goal, "context": context or ""}
        )
        return Plan(**out["plan"])

    async def areplan(
        self, goal: str, current_plan: Plan, feedback: str, context: str | None = None
    ) -> Plan:
        if context is None and self.retriever is not None:
            context = await self.retriever(goal)
        out = await self.graph.ainvoke(
            {
                "mode": "replan",
                "goal": goal,
                "current_plan": current_plan.model_dump(mode="json"),
                "feedback": feedback,
                "context": context or "",
            }
        )
        return Plan(**out["plan"])


def get_planner_agent() -> PlannerAgent:
    return PlannerAgent()
