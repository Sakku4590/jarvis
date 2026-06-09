"""WhatsApp service via the Twilio WhatsApp API.

Twilio is the compliant, official path for programmatic WhatsApp (unlike the
unofficial web libraries that get numbers banned). Credentials are Twilio
account-level (Account SID + Auth Token), read from config, so there is no
per-user OAuth here. httpx is used directly; no SDK.

Pure helpers (number normalization, request param building, send-time
validation) are testable without network; only `_post` touches Twilio.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_BASE = "https://api.twilio.com/2010-04-01"


class WhatsAppError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


class NotConfigured(WhatsAppError):
    def __init__(self) -> None:
        super().__init__("not_configured",
                         "Twilio is not configured (account sid / auth token / from)")


def to_whatsapp(number: str) -> str:
    return number if number.startswith("whatsapp:") else f"whatsapp:{number}"


def validate_send_at(send_at: str) -> str:
    try:
        dt = datetime.fromisoformat(send_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WhatsAppError("bad_send_at", f"send_at is not ISO 8601: {send_at}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt <= datetime.now(timezone.utc):
        raise WhatsAppError("bad_send_at", "send_at must be in the future")
    return dt.isoformat()


def build_message_params(
    from_: str | None, to: str, body: str,
    messaging_service_sid: str | None = None, send_at: str | None = None,
) -> dict:
    params: dict = {"To": to_whatsapp(to), "Body": body}
    if send_at:
        # Scheduled sends require a Messaging Service, not a From number.
        params["MessagingServiceSid"] = messaging_service_sid
        params["ScheduleType"] = "fixed"
        params["SendAt"] = send_at
    else:
        params["From"] = to_whatsapp(from_) if from_ else None
    return {k: v for k, v in params.items() if v is not None}


class WhatsAppService(ABC):
    @abstractmethod
    async def send(self, to: str, body: str) -> dict: ...

    @abstractmethod
    async def schedule(self, to: str, body: str, send_at: str) -> dict: ...

    @abstractmethod
    async def broadcast(self, recipients: list[str], body: str) -> dict: ...


class TwilioWhatsAppService(WhatsAppService):
    def __init__(self) -> None:
        s = get_settings()
        self.sid = s.twilio_account_sid
        self.token = s.twilio_auth_token
        self.from_ = s.twilio_whatsapp_from
        self.messaging_service_sid = s.twilio_messaging_service_sid

    def _require(self) -> None:
        if not self.sid or not self.token or not self.from_:
            raise NotConfigured()

    async def _post(self, params: dict) -> dict:
        url = f"{_BASE}/Accounts/{self.sid}/Messages.json"
        async with httpx.AsyncClient(timeout=20) as c:
            resp = await c.post(url, data=params, auth=(self.sid, self.token))
        if resp.is_success:
            data = resp.json()
            return {"sid": data.get("sid"), "status": data.get("status"),
                    "to": data.get("to")}
        self._raise(resp)

    @staticmethod
    def _raise(resp: httpx.Response) -> None:
        code = resp.status_code
        detail = ""
        try:
            detail = resp.json().get("message", "")
        except Exception:  # noqa: BLE001
            detail = resp.text[:200]
        if code == 401:
            raise WhatsAppError("unauthorized", "invalid Twilio credentials")
        if code == 429:
            raise WhatsAppError("rate_limited", "Twilio rate limit exceeded")
        if code == 400:
            raise WhatsAppError("bad_request", detail or "invalid request")
        raise WhatsAppError("api_error", f"Twilio error {code}: {detail}")

    async def send(self, to: str, body: str) -> dict:
        self._require()
        return await self._post(build_message_params(self.from_, to, body))

    async def schedule(self, to: str, body: str, send_at: str) -> dict:
        self._require()
        if not self.messaging_service_sid:
            raise WhatsAppError(
                "no_messaging_service",
                "scheduling requires TWILIO_MESSAGING_SERVICE_SID")
        when = validate_send_at(send_at)
        params = build_message_params(
            None, to, body,
            messaging_service_sid=self.messaging_service_sid, send_at=when)
        result = await self._post(params)
        result["scheduled_for"] = when
        return result

    async def broadcast(self, recipients: list[str], body: str) -> dict:
        self._require()
        results = []
        for to in recipients:
            try:
                r = await self.send(to, body)
                results.append({"to": to, "ok": True, **r})
            except WhatsAppError as exc:
                results.append({"to": to, "ok": False, "error": str(exc)})
        sent = sum(1 for r in results if r["ok"])
        return {"total": len(recipients), "sent": sent,
                "failed": len(recipients) - sent, "results": results}


def get_whatsapp_service() -> WhatsAppService:
    return TwilioWhatsAppService()
