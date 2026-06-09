"""Coding Agent tests: the tool-calling loop with a scripted LLM and a real
sandbox. Verifies generation feeds execution, the execution gate fires, and the
read-only tools (review, debug) return their content."""

import pytest

from app.agents.coding_agent import CodingAgent, code_registry
from app.services.code_sandbox import SubprocessSandbox


class FakeCodingLLM:
    def __init__(self, decisions: list[dict], text: str = "") -> None:
        self._decisions = list(decisions)
        self._text = text

    async def complete_json(self, system, user, temperature=0.0) -> dict:
        if not self._decisions:
            return {"action": "finish", "answer": "done"}
        return self._decisions.pop(0)

    async def complete_text(self, system, user, temperature=0.3) -> str:
        return self._text


def _agent(decisions, text="") -> CodingAgent:
    llm = FakeCodingLLM(decisions, text)
    reg = code_registry(SubprocessSandbox(), llm)
    return CodingAgent(registry=reg, llm=llm)


async def test_generate_then_execute_with_approval():
    code = "print('hi from sandbox')"
    agent = _agent([
        {"action": "call", "tool": "code.generate", "args": {"task": "print hi"}},
        {"action": "call", "tool": "code.execute", "args": {"code": code}},
        {"action": "finish", "answer": "Generated and ran the code."},
    ], text=code)

    out = await agent.arun("u1", "write a script that prints hi and run it", approved=True)

    gen, run = out["calls"][0], out["calls"][1]
    assert gen["data"]["code"] == code
    assert run["status"] == "success"
    assert "hi from sandbox" in run["data"]["stdout"]
    assert out["answer"] == "Generated and ran the code."


async def test_execute_is_gated_without_approval():
    agent = _agent([
        {"action": "call", "tool": "code.execute", "args": {"code": "print(1)"}},
        {"action": "finish", "answer": "Execution needs approval."},
    ])
    out = await agent.arun("u1", "run this", approved=False)
    assert out["calls"][0]["status"] == "pending_approval"


async def test_review_returns_text():
    agent = _agent([
        {"action": "call", "tool": "code.review", "args": {"code": "x = 1"}},
        {"action": "finish", "answer": "Reviewed."},
    ], text="No bugs; consider a docstring.")
    out = await agent.arun("u1", "review my code")
    assert out["calls"][0]["data"]["review"] == "No bugs; consider a docstring."


async def test_debug_returns_analysis():
    agent = _agent([
        {"action": "call", "tool": "code.debug",
         "args": {"code": "1/0", "error": "ZeroDivisionError"}},
        {"action": "finish", "answer": "Explained."},
    ], text="Division by zero; guard the denominator before dividing.")
    out = await agent.arun("u1", "why does this crash")
    assert "Division by zero" in out["calls"][0]["data"]["analysis"]


async def test_failed_execution_surfaces_error():
    agent = _agent([
        {"action": "call", "tool": "code.execute",
         "args": {"code": "raise RuntimeError('nope')"}},
        {"action": "finish", "answer": "It failed."},
    ])
    out = await agent.arun("u1", "run broken code", approved=True)
    call = out["calls"][0]
    assert call["status"] == "success"          # the tool ran
    assert call["data"]["ok"] is False          # but the code itself failed
    assert "RuntimeError" in call["data"]["stderr"]
