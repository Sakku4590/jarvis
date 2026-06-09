"""End-to-end Supervisor tests.

Drives the real orchestration graph, real planner, real tool pipeline, and real
selector. Only the LLM and the memory agent are faked. Covers all three routes
and the risk gate firing mid-plan.
"""

import pytest

from app.agents.supervisor import SupervisorAgent


class FakeLLM:
    def __init__(self, classify: dict, plan: dict, text: str) -> None:
        self.classify = classify
        self.plan = plan
        self.text = text

    async def complete_json(self, system, user, temperature=0.0) -> dict:
        if "route a user's message" in system:
            return self.classify
        if "planning agent" in system:
            return self.plan
        return {}  # selector ambiguity -> deterministic fallback

    async def complete_text(self, system, user, temperature=0.3) -> str:
        return self.text


class FakeMemory:
    async def aretrieve(self, user_id, query) -> dict:
        return {"memory_block": "", "retrieved": []}


def _agent(classify, plan=None, text="ok") -> SupervisorAgent:
    llm = FakeLLM(classify, plan or {"steps": []}, text)
    return SupervisorAgent(llm=llm, memory_agent=FakeMemory(), memory_retriever=None)


async def test_chat_route_answers_directly():
    agent = _agent({"route": "chat"}, text="The capital of France is Paris.")
    out = await agent.arun("u1", "what is the capital of France?")
    assert out["route"] == "chat"
    assert out["answer"] == "The capital of France is Paris."
    assert not out.get("results")  # no tools on the chat path


async def test_single_route_runs_one_tool():
    agent = _agent({"route": "single", "capability": "calendar"}, text="done")
    out = await agent.arun("u1", "put a dentist appointment on my calendar")
    assert out["route"] == "single"
    results = out["results"]
    assert len(results) == 1
    assert results[0]["tool"] == "calendar.create"
    assert results[0]["ok"] is True


async def test_plan_route_executes_and_risk_gate_holds_send():
    plan = {"steps": [
        {"id": "s1", "description": "find the contract", "capability": "file",
         "inputs": {"action": "search", "query": "contract"}, "depends_on": []},
        {"id": "s2", "description": "email it", "capability": "email",
         "inputs": {"action": "send", "to": "john@x.com", "subject": "Contract",
                    "body": "Please find the contract details attached."},
         "depends_on": ["s1"]},
    ]}
    agent = _agent({"route": "plan"}, plan=plan, text="summary")
    out = await agent.arun("u1", "find the contract and email it to John")

    assert out["route"] == "plan"
    by_step = {r["step_id"]: r for r in out["results"]}
    assert by_step["s1"]["status"] == "success"          # read ran
    assert by_step["s2"]["status"] == "pending_approval"  # send held by the gate


async def test_plan_route_send_clears_with_approval():
    plan = {"steps": [
        {"id": "s1", "description": "email it", "capability": "email",
         "inputs": {"action": "send", "to": "john@x.com"}, "depends_on": []},
    ]}
    agent = _agent({"route": "plan"}, plan=plan, text="sent")
    out = await agent.arun("u1", "email John", approved=True)
    by_step = {r["step_id"]: r for r in out["results"]}
    # email.send is now a real, credentialed tool. With approval the gate is
    # cleared and execution is attempted (it then fails for lack of a connected
    # account in this test). The point is the gate no longer holds it.
    assert by_step["s1"]["status"] != "pending_approval"


async def test_plan_route_invalid_plan_is_not_executed():
    plan = {"steps": [
        {"id": "s1", "description": "x", "capability": "teleport",
         "inputs": {}, "depends_on": ["s9"]},
    ]}
    agent = _agent({"route": "plan"}, plan=plan, text="cannot")
    out = await agent.arun("u1", "do the impossible")
    # Invalid plan goes straight to synthesis; nothing executed.
    assert out["plan"]["status"] == "invalid"
    assert not out.get("results")
