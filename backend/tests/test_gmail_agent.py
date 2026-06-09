"""Phase 8 tests: credential crypto, message building, store, and the agent loop.

No Google API or network: the agent runs against a fake GmailService, and the
crypto / MIME / store pieces are exercised directly.
"""

import base64

import pytest

from app.agents.gmail_agent import GmailAgent, gmail_registry
from app.core.crypto import DecryptionError, decrypt, encrypt
from app.integrations.credential_store import InMemoryCredentialStore
from app.services.gmail_service import GmailService, NotConnected, build_raw_message


# --- credential crypto ----------------------------------------------------

def test_encrypt_decrypt_roundtrip():
    secret = '{"token": "abc", "refresh_token": "xyz"}'
    blob = encrypt(secret)
    assert blob != secret  # stored ciphertext is not the plaintext
    assert decrypt(blob) == secret


def test_tampered_ciphertext_fails():
    blob = encrypt("sensitive")
    with pytest.raises(DecryptionError):
        decrypt(blob[:-2] + "xx")


# --- MIME builder ---------------------------------------------------------

def test_build_raw_message_is_decodable():
    raw = build_raw_message("a@b.com", "Hi", "Hello there")
    decoded = base64.urlsafe_b64decode(raw.encode()).decode()
    assert "To: a@b.com" in decoded
    assert "Subject: Hi" in decoded
    assert "Hello there" in decoded


def test_build_raw_message_threads_reply():
    raw = build_raw_message("a@b.com", "Re: Hi", "ok", in_reply_to="<id-123>")
    decoded = base64.urlsafe_b64decode(raw.encode()).decode()
    assert "In-Reply-To: <id-123>" in decoded
    assert "References: <id-123>" in decoded


# --- in-memory credential store -------------------------------------------

async def test_credential_store_save_load_delete():
    store = InMemoryCredentialStore()
    assert await store.load("u1", "gmail") is None
    await store.save("u1", "gmail", {"token": "t"})
    assert (await store.load("u1", "gmail"))["token"] == "t"
    await store.delete("u1", "gmail")
    assert await store.load("u1", "gmail") is None


# --- fake gmail service + agent -------------------------------------------

class FakeGmail(GmailService):
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected
        self.calls: list[str] = []

    def _check(self):
        if not self.connected:
            raise NotConnected()

    async def list_inbox(self, user_id, max_results=20):
        self._check(); self.calls.append("list_inbox")
        return {"messages": [{"id": "1", "from": "bob@x.com", "subject": "Hi"}], "count": 1}

    async def search(self, user_id, query, max_results=20):
        self._check(); self.calls.append("search")
        return {"query": query, "messages": [{"id": "2", "subject": "Invoice"}], "count": 1}

    async def send(self, user_id, to, subject, body):
        self._check(); self.calls.append("send")
        return {"sent": True, "id": "99", "to": to}

    async def draft_reply(self, user_id, message_id, body):
        self._check(); self.calls.append("draft_reply")
        return {"draft_id": "d1", "to": "bob@x.com", "subject": "Re: Hi"}


def _agent(decisions, service=None) -> tuple[GmailAgent, FakeGmail]:
    svc = service or FakeGmail()

    class ScriptedLLM:
        def __init__(self, d): self._d = list(d)
        async def complete_json(self, system, user, temperature=0.0):
            return self._d.pop(0) if self._d else {"action": "finish", "answer": "done"}
        async def complete_text(self, system, user, temperature=0.3):
            return ""

    return GmailAgent(registry=gmail_registry(svc), llm=ScriptedLLM(decisions)), svc


async def test_agent_searches_and_reads():
    agent, svc = _agent([
        {"action": "call", "tool": "email.search", "args": {"query": "is:unread"}},
        {"action": "call", "tool": "email.read_inbox", "args": {"max_results": 5}},
        {"action": "finish", "answer": "You have unread mail."},
    ])
    out = await agent.arun("u1", "what unread mail do I have")
    assert svc.calls == ["search", "list_inbox"]
    assert out["calls"][0]["data"]["count"] == 1
    assert out["answer"] == "You have unread mail."


async def test_agent_send_is_gated_then_allowed():
    decisions = [
        {"action": "call", "tool": "email.send",
         "args": {"to": "a@b.com", "subject": "Hi", "body": "hello"}},
        {"action": "finish", "answer": "tried"},
    ]
    agent, svc = _agent(decisions)
    out = await agent.arun("u1", "email a@b.com", approved=False)
    assert out["calls"][0]["status"] == "pending_approval"
    assert "send" not in svc.calls

    agent2, svc2 = _agent(decisions)
    out2 = await agent2.arun("u1", "email a@b.com", approved=True)
    assert out2["calls"][0]["status"] == "success"
    assert svc2.calls == ["send"]


async def test_agent_draft_reply_not_gated():
    agent, svc = _agent([
        {"action": "call", "tool": "email.draft_reply",
         "args": {"message_id": "1", "body": "thanks"}},
        {"action": "finish", "answer": "Drafted."},
    ])
    out = await agent.arun("u1", "reply to that message")
    assert out["calls"][0]["status"] == "success"  # WRITE, not gated
    assert out["calls"][0]["data"]["draft_id"] == "d1"


async def test_agent_handles_not_connected():
    agent, _ = _agent([
        {"action": "call", "tool": "email.read_inbox", "args": {}},
        {"action": "finish", "answer": "Not connected."},
    ], service=FakeGmail(connected=False))
    out = await agent.arun("u1", "check my mail")
    call = out["calls"][0]
    assert call["status"] == "error"
    assert "not_connected" in call["error"]["message"]
