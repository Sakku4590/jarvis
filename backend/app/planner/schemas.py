"""Planner schemas.

The shapes a plan moves through. A Plan is an ordered set of PlanSteps forming
a dependency DAG. The planner produces it; a later executor (other agents, out
of scope here) would walk `order`, run each step, and write `result`/`status`
back. Keeping `status`/`result` on the step now means replanning can reason
about partial progress without a schema change.
"""

from enum import Enum

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStatus(str, Enum):
    DRAFT = "draft"      # produced by the LLM, not yet validated
    READY = "ready"      # validated: acyclic, references resolve, order computed
    INVALID = "invalid"  # validation found problems (see Plan.errors)


class PlanStep(BaseModel):
    id: str                                   # short stable id, e.g. "s1"
    description: str
    capability: str                           # must exist in the registry
    inputs: dict = Field(default_factory=dict)
    # ids of steps that must complete before this one. Inputs may reference a
    # dependency's output with the convention "$<step_id>.output".
    depends_on: list[str] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: dict | None = None


class Plan(BaseModel):
    goal: str
    steps: list[PlanStep] = Field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    order: list[str] = Field(default_factory=list)   # topological execution order
    errors: list[str] = Field(default_factory=list)  # validation messages

    def step(self, step_id: str) -> PlanStep | None:
        return next((s for s in self.steps if s.id == step_id), None)


class ReplanRequest(BaseModel):
    goal: str
    current_plan: Plan
    feedback: str  # what happened: a failure, new information, a changed goal
    context: str = ""
