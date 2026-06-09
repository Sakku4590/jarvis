"""File Agent tests: the tool-calling loop against an isolated workspace.

Only the LLM is faked, returning a scripted sequence of decisions. The
FileService, tools, and pipeline are all real, so these verify that the agent's
tool calls actually touch the sandboxed filesystem and that the delete gate
fires.
"""

import pytest

from app.agents.file_agent import FileAgent, file_registry
from app.services.file_service import FileService, NotFound


class ScriptedLLM:
    """Returns queued JSON decisions in order; raises if it runs out."""

    def __init__(self, decisions: list[dict]) -> None:
        self._decisions = list(decisions)

    async def complete_json(self, system, user, temperature=0.0) -> dict:
        if not self._decisions:
            return {"action": "finish", "answer": "done (out of script)"}
        return self._decisions.pop(0)


def _agent(tmp_path, decisions) -> tuple[FileAgent, FileService]:
    svc = FileService(root=tmp_path)
    reg = file_registry(svc)
    agent = FileAgent(registry=reg, llm=ScriptedLLM(decisions))
    return agent, svc


async def test_agent_creates_then_reads(tmp_path):
    agent, svc = _agent(tmp_path, [
        {"action": "call", "tool": "file.create",
         "args": {"path": "hello.txt", "content": "hi there"}},
        {"action": "call", "tool": "file.read", "args": {"path": "hello.txt"}},
        {"action": "finish", "answer": "Created and read hello.txt."},
    ])
    out = await agent.arun("u1", "create hello.txt then read it back")

    assert out["answer"] == "Created and read hello.txt."
    assert svc.read("hello.txt")["content"] == "hi there"
    statuses = [c["status"] for c in out["calls"]]
    assert statuses == ["success", "success"]
    assert out["calls"][1]["data"]["content"] == "hi there"


async def test_agent_search(tmp_path):
    svc = FileService(root=tmp_path)
    svc.create("budget-2026.csv", "x")
    svc.create("readme.md", "y")
    reg = file_registry(svc)
    agent = FileAgent(registry=reg, llm=ScriptedLLM([
        {"action": "call", "tool": "file.search", "args": {"query": "budget"}},
        {"action": "finish", "answer": "Found 1 file."},
    ]))
    out = await agent.arun("u1", "find my budget file")
    matches = out["calls"][0]["data"]["matches"]
    assert {m["name"] for m in matches} == {"budget-2026.csv"}


async def test_agent_delete_is_gated_then_allowed(tmp_path):
    # Without approval: delete is held, file survives.
    agent, svc = _agent(tmp_path, [
        {"action": "call", "tool": "file.delete", "args": {"path": "secret.txt"}},
        {"action": "finish", "answer": "Delete needs approval."},
    ])
    svc.create("secret.txt", "classified")
    out = await agent.arun("u1", "delete secret.txt", approved=False)
    assert out["calls"][0]["status"] == "pending_approval"
    assert svc.read("secret.txt")["content"] == "classified"  # still there

    # With approval: delete goes through.
    agent2, _ = (FileAgent(registry=file_registry(svc), llm=ScriptedLLM([
        {"action": "call", "tool": "file.delete", "args": {"path": "secret.txt"}},
        {"action": "finish", "answer": "Deleted."},
    ])), svc)
    out2 = await agent2.arun("u1", "delete secret.txt", approved=True)
    assert out2["calls"][0]["status"] == "success"
    with pytest.raises(NotFound):
        svc.read("secret.txt")


async def test_agent_stops_at_iteration_cap(tmp_path):
    # Model never finishes; the cap must stop the loop.
    svc = FileService(root=tmp_path)
    reg = file_registry(svc)
    never_finish = [{"action": "call", "tool": "file.search", "args": {"query": "x"}}] * 50
    agent = FileAgent(registry=reg, llm=ScriptedLLM(never_finish), max_iters=3)
    out = await agent.arun("u1", "loop forever")
    # Capped at 3 think iterations -> at most 3 calls, then forced finish.
    assert len(out["calls"]) <= 3
    assert out["answer"]
