"""Phase 10 tests: WhatsApp helpers and the agent loop with a fake service."""

import pytest

from app.agents.whatsapp_agent import WhatsAppAgent, whatsapp_registry
from app.services.whatsapp_service import (
    NotConfigured,
    WhatsAppError,
    WhatsAppService,
    build_message_params,
    to_whatsapp,
    validate_send_at,
)


# --- pure helpers ---------------------------------------------------------

def test_to_whatsapp_prefix():
    assert to_whatsapp("+14155550123") == "whatsapp:+14155550123"
    assert to_whatsapp("whatsapp:+14155550123") == "whatsapp:+14155550123"


def test_build_params_immediate_vs_scheduled():
    immediate = build_message_params("whatsapp:+1000", "+1999", "hi")
    assert immediate["From"] == "whatsapp:+1000" and immediate["To"] == "whatsapp:+1999"
    assert "SendAt" not in immediate

    scheduled = build_message_params(None, "+1999", "hi",
                                     messaging_service_sid="MGxxx", send_at="2999-01-01T00:00:00+00:00")
    assert scheduled["ScheduleType"] == "fixed"
    assert scheduled["MessagingServiceSid"] == "MGxxx"
    assert "From" not in scheduled


def test_validate_send_at_rejects_past():
    with pytest.raises(WhatsAppError):
        validate_send_at("2000-01-01T00:00:00+00:00")
    with pytest.raises(WhatsAppError):
        validate_send_at("not-a-date")
    assert validate_send_at("2999-01-01T00:00:00+00:00").startswith("2999")


# --- fake service + agent -------------------------------------------------

class FakeWhatsApp(WhatsAppService):
    def __init__(self, configured: bool = True) -> None:
        self.configured = configured
        self.calls: list[str] = []

    def _check(self):
        if not self.configured:
            raise NotConfigured()

    async def send(self, to, body):
        self._check(); self.calls.append("send")
        return {"sid": "SM1", "status": "queued", "to": to}

    async def schedule(self, to, body, send_at):
        self._check(); self.calls.append("schedule")
        return {"sid": "SM2", "status": "scheduled", "to": to, "scheduled_for": send_at}

    async def broadcast(self, recipients, body):
        self._check(); self.calls.append("broadcast")
        return {"total": len(recipients), "sent": len(recipients), "failed": 0}


def _agent(decisions, service=None) -> tuple[WhatsAppAgent, FakeWhatsApp]:
    svc = service or FakeWhatsApp()

    class ScriptedLLM:
        def __init__(self, d): self._d = list(d)
        async def complete_json(self, system, user, temperature=0.0):
            return self._d.pop(0) if self._d else {"action": "finish", "answer": "done"}
        async def complete_text(self, system, user, temperature=0.3):
            return ""

    return WhatsAppAgent(registry=whatsapp_registry(svc), llm=ScriptedLLM(decisions)), svc


async def test_send_is_gated_then_allowed():
    decisions = [
        {"action": "call", "tool": "messaging.send",
         "args": {"to": "+1999", "body": "hello"}},
        {"action": "finish", "answer": "tried"},
    ]
    agent, svc = _agent(decisions)
    out = await agent.arun("u1", "message bob", approved=False)
    assert out["calls"][0]["status"] == "pending_approval"
    assert "send" not in svc.calls

    agent2, svc2 = _agent(decisions)
    out2 = await agent2.arun("u1", "message bob", approved=True)
    assert out2["calls"][0]["status"] == "success"
    assert svc2.calls == ["send"]
    assert out2["calls"][0]["data"]["sid"] == "SM1"


async def test_schedule():
    agent, svc = _agent([
        {"action": "call", "tool": "messaging.schedule",
         "args": {"to": "+1999", "body": "reminder", "send_at": "2999-01-01T00:00:00+00:00"}},
        {"action": "finish", "answer": "scheduled"},
    ])
    out = await agent.arun("u1", "remind me later", approved=True)
    assert svc.calls == ["schedule"]
    assert out["calls"][0]["data"]["status"] == "scheduled"


async def test_broadcast():
    agent, svc = _agent([
        {"action": "call", "tool": "messaging.broadcast",
         "args": {"recipients": ["+1", "+2", "+3"], "body": "notice"}},
        {"action": "finish", "answer": "broadcast sent"},
    ])
    out = await agent.arun("u1", "notify everyone", approved=True)
    assert svc.calls == ["broadcast"]
    assert out["calls"][0]["data"]["sent"] == 3


async def test_not_configured():
    agent, _ = _agent([
        {"action": "call", "tool": "messaging.send", "args": {"to": "+1", "body": "x"}},
        {"action": "finish", "answer": "not configured"},
    ], service=FakeWhatsApp(configured=False))
    out = await agent.arun("u1", "send a message", approved=True)
    assert out["calls"][0]["status"] == "error"
    assert "not_configured" in out["calls"][0]["error"]["message"]
