"""Orchestrator tests: the unified multi-agent workflow.

Real classifier, planner, and delegation logic; the LLM and the specialist
agents are fakes. A fake agent records the instruction it was delegated and
returns canned calls, so we can verify routing, delegation order, cross-step
flow, and that a held-for-approval step blocks its dependents.
"""

import pytest

from app.agents.agent_registry import AgentRegistry
from app.agents.orchestrator import Orchestrator


class FakeAgent:
    def __init__(self, answer="done", status="success") -> None:
        self.answer = answer
        self.calls = [{"status": status}]
        self.seen: list[tuple[str, bool]] = []

    async def arun(self, user_id, instruction, approved=False) -> dict:
        self.seen.append((instruction, approved))
        return {"answer": self.answer, "calls": self.calls}


class FakeLLM:
    def __init__(self, classify, plan, text="ok") -> None:
        self.classify, self.plan, self.text = classify, plan, text

    async def complete_json(self, system, user, temperature=0.0) -> dict:
        if "route a user's message" in system:
            return self.classify
        if "planning agent" in system:
            return self.plan
        return {}

    async def complete_text(self, system, user, temperature=0.3) -> str:
        return self.text


def _orch(classify, plan=None, agents=None, text="ok") -> tuple[Orchestrator, dict]:
    agents = agents or {"file": FakeAgent("listed"), "email": FakeAgent("drafted")}
    orch = Orchestrator(
        llm=FakeLLM(classify, plan or {"steps": []}, text),
        agents=AgentRegistry(agents),
        memory_retriever=None,
    )
    return orch, agents


async def test_chat_route():
    orch, _ = _orch({"route": "chat"}, text="Hello there.")
    out = await orch.arun("u1", "hi")
    assert out["route"] == "chat" and out["answer"] == "Hello there."
    assert not out.get("results")


async def test_single_route_delegates_to_agent():
    orch, agents = _orch({"route": "single", "capability": "file"})
    out = await orch.arun("u1", "list my files")
    assert out["route"] == "single"
    assert agents["file"].seen[0][0] == "list my files"   # delegated instruction
    assert out["results"][0]["delegate"] == "agent"
    assert out["results"][0]["status"] == "success"


async def test_plan_route_delegates_across_agents_in_order():
    plan = {"steps": [
        {"id": "s1", "description": "find the contract", "capability": "file",
         "inputs": {"action": "search"}, "depends_on": []},
        {"id": "s2", "description": "draft an email about it", "capability": "email",
         "inputs": {"note": "$s1.output"}, "depends_on": ["s1"]},
    ]}
    orch, agents = _orch({"route": "plan"}, plan=plan)
    out = await orch.arun("u1", "find the contract and draft an email")

    assert out["route"] == "plan"
    assert [r["step_id"] for r in out["results"]] == ["s1", "s2"]
    assert all(r["delegate"] == "agent" for r in out["results"])
    # s2's instruction carried s1's output via the $s1.output reference.
    assert "listed" in agents["email"].seen[0][0]


async def test_held_step_blocks_dependents():
    plan = {"steps": [
        {"id": "s1", "description": "send mail", "capability": "email",
         "inputs": {}, "depends_on": []},
        {"id": "s2", "description": "then file it", "capability": "file",
         "inputs": {}, "depends_on": ["s1"]},
    ]}
    agents = {"email": FakeAgent("held", status="pending_approval"),
              "file": FakeAgent("filed")}
    orch, agents = _orch({"route": "plan"}, plan=plan, agents=agents)
    out = await orch.arun("u1", "send then file", approved=False)

    by_step = {r["step_id"]: r for r in out["results"]}
    assert by_step["s1"]["status"] == "pending_approval"
    assert by_step["s2"]["status"] == "skipped"          # dependent skipped
    assert agents["file"].seen == []                      # file agent never ran


async def test_invalid_plan_skips_execution():
    plan = {"steps": [
        {"id": "s1", "description": "x", "capability": "teleport",
         "inputs": {}, "depends_on": ["s9"]},
    ]}
    orch, agents = _orch({"route": "plan"}, plan=plan)
    out = await orch.arun("u1", "do the impossible")
    assert out["plan"]["status"] == "invalid"
    assert not out.get("results")
    assert agents["file"].seen == []


async def test_capability_without_agent_falls_back_to_tools():
    # calendar has no specialist agent -> falls back to the (stub) calendar tool.
    plan = {"steps": [
        {"id": "s1", "description": "add an event", "capability": "calendar",
         "inputs": {"action": "create", "title": "Lunch"}, "depends_on": []},
    ]}
    orch, _ = _orch({"route": "plan"}, plan=plan)
    out = await orch.arun("u1", "put lunch on my calendar", approved=True)
    r = out["results"][0]
    assert r["delegate"] == "tool"
    assert r["status"] == "success"  # the calendar stub returns success
