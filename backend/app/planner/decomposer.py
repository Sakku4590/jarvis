"""Goal decomposition.

Turns a natural-language goal into draft PlanSteps using the LLM, and revises an
existing plan given execution feedback. Validation and ordering happen
downstream in validation.py, so this layer only has to produce candidate steps;
it never has to be trusted to get dependencies right on its own.

Injectable LLM (anything with `async complete_json(system, user)`), so tests run
with a canned model.
"""

import json

from app.core.config import get_settings
from app.core.llm import LLMClient
from app.core.logging import get_logger
from app.planner.capabilities import CapabilityRegistry
from app.planner.schemas import Plan, PlanStep

log = get_logger(__name__)


def _plan_system(registry: CapabilityRegistry, max_steps: int) -> str:
    return f"""You are a planning agent. Break a user's goal into an ordered \
list of concrete steps that other agents will execute.

Available capabilities (use ONLY these keys for "capability"):
{registry.catalog_text()}

Rules:
- Emit at most {max_steps} steps. Fewer is better; do not pad.
- Give each step a short id: s1, s2, s3, ... in the order you write them.
- "depends_on" lists the ids of steps that must finish first. Use it whenever a \
step needs an earlier step's output. Reference that output inside "inputs" with \
the convention "$<step_id>.output".
- The dependency graph must be acyclic.
- If the goal is a single action, a one-step plan is correct.

Reply with a single JSON object:
{{"steps": [{{"id": "s1", "description": "...", "capability": "...", \
"inputs": {{}}, "depends_on": []}}]}}"""


_REPLAN_SYSTEM_SUFFIX = """

You are REVISING an existing plan. You are given the original goal, the current \
plan with each step's status and result, and feedback about what happened (a \
failure, new information, or a changed goal). Produce a new full plan for the \
remaining work. Keep already-completed steps only if they still need to be \
represented; do not redo work that succeeded. Same JSON output format and same \
rules as before."""


class GoalDecomposer:
    def __init__(
        self,
        llm: LLMClient | None = None,
        registry: CapabilityRegistry | None = None,
        max_steps: int | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.registry = registry or CapabilityRegistry()
        self.max_steps = max_steps or get_settings().planner_max_steps

    async def plan(self, goal: str, context: str = "") -> list[PlanStep]:
        system = _plan_system(self.registry, self.max_steps)
        user = self._user_block(goal, context)
        data = await self.llm.complete_json(system, user)
        return self._parse_steps(data)

    async def replan(
        self, goal: str, current_plan: Plan, feedback: str, context: str = ""
    ) -> list[PlanStep]:
        system = _plan_system(self.registry, self.max_steps) + _REPLAN_SYSTEM_SUFFIX
        user = self._user_block(
            goal,
            context,
            extra={
                "feedback": feedback,
                "current_plan": current_plan.model_dump(mode="json"),
            },
        )
        data = await self.llm.complete_json(system, user)
        return self._parse_steps(data)

    def _user_block(self, goal: str, context: str, extra: dict | None = None) -> str:
        payload: dict = {"goal": goal}
        if context:
            payload["context"] = context
        if extra:
            payload.update(extra)
        return json.dumps(payload)

    def _parse_steps(self, data: dict) -> list[PlanStep]:
        steps: list[PlanStep] = []
        for i, raw in enumerate(data.get("steps", []), start=1):
            try:
                raw.setdefault("id", f"s{i}")
                steps.append(PlanStep(**raw))
            except Exception as exc:  # noqa: BLE001
                log.warning("planner.bad_step", raw=raw, error=str(exc))
        # Truncate defensively even if the model ignored the cap.
        if len(steps) > self.max_steps:
            steps = steps[: self.max_steps]
        log.info("planner.decompose", count=len(steps))
        return steps
