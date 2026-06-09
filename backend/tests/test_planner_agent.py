"""End-to-end Planner Agent tests.

Drives the real LangGraph graph and the real validation logic; only the LLM is
canned. Covers the plan flow, the replan flow, and that an LLM-emitted bad plan
still gets caught as invalid rather than passed through.
"""

import pytest

from app.planner.agent import PlannerAgent
from app.planner.schemas import Plan, PlanStatus


class FakeLLM:
    """Returns a canned steps payload, switching on the plan vs replan prompt."""

    def __init__(self, plan_payload: dict, replan_payload: dict | None = None) -> None:
        self.plan_payload = plan_payload
        self.replan_payload = replan_payload or plan_payload

    async def complete_json(self, system, user, temperature=0.0) -> dict:
        if "REVISING an existing plan" in system:
            return self.replan_payload
        return self.plan_payload


async def test_plan_flow_produces_ready_ordered_plan():
    payload = {"steps": [
        {"id": "s1", "description": "find the contract",
         "capability": "file", "inputs": {"action": "search"}, "depends_on": []},
        {"id": "s2", "description": "summarize it",
         "capability": "file", "inputs": {"in": "$s1.output"}, "depends_on": ["s1"]},
        {"id": "s3", "description": "email John the summary",
         "capability": "email", "inputs": {"to": "john@x.com"}, "depends_on": ["s2"]},
    ]}
    agent = PlannerAgent(llm=FakeLLM(payload))
    plan = await agent.aplan("find the contract, summarize it, and email John")

    assert isinstance(plan, Plan)
    assert plan.status is PlanStatus.READY
    assert plan.order == ["s1", "s2", "s3"]
    assert len(plan.steps) == 3


async def test_replan_flow_revises_plan():
    plan_payload = {"steps": [
        {"id": "s1", "description": "email John", "capability": "email",
         "inputs": {}, "depends_on": []},
    ]}
    replan_payload = {"steps": [
        {"id": "s1", "description": "look up John's email address",
         "capability": "memory", "inputs": {"action": "retrieve"}, "depends_on": []},
        {"id": "s2", "description": "email John", "capability": "email",
         "inputs": {"to": "$s1.output"}, "depends_on": ["s1"]},
    ]}
    agent = PlannerAgent(llm=FakeLLM(plan_payload, replan_payload))

    first = await agent.aplan("email John")
    assert first.status is PlanStatus.READY and len(first.steps) == 1

    revised = await agent.areplan(
        "email John", first, feedback="send failed: no address on file"
    )
    assert revised.status is PlanStatus.READY
    assert revised.order == ["s1", "s2"]
    assert revised.step("s1").capability == "memory"


async def test_bad_llm_plan_is_marked_invalid():
    # LLM emits a step that depends on a nonexistent step and uses a bad capability.
    payload = {"steps": [
        {"id": "s1", "description": "do a thing", "capability": "teleport",
         "inputs": {}, "depends_on": ["s9"]},
    ]}
    agent = PlannerAgent(llm=FakeLLM(payload))
    plan = await agent.aplan("do something impossible")

    assert plan.status is PlanStatus.INVALID
    assert plan.errors  # surfaced, not silently executed
