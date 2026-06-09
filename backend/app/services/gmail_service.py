"""Gmail service.

Wraps the Gmail API behind an interface (GmailService) so tests use a fake. The
real implementation (GmailApiService) loads encrypted credentials per user,
refreshes them when expired (persisting the refreshed token), and maps Gmail
HTTP errors to clean GmailError exceptions that the tool pipeline turns into
error envelopes. google libraries are imported lazily.

`build_raw_message` is pure (stdlib only) and unit-tested independently of the
network.
"""

import base64
from abc import ABC, abstractmethod
from email.mime.text import MIMEText

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.credential_store import CredentialStore, get_credential_store
from app.integrations.google_oauth import credentials_from_dict, creds_to_dict

log = get_logger(__name__)


class GmailError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


class NotConnected(GmailError):
    def __init__(self) -> None:
        super().__init__("not_connected", "Gmail is not connected; authorize first")


def build_raw_message(
    to: str, subject: str, body: str,
    sender: str | None = None, in_reply_to: str | None = None,
) -> str:
    """Build an RFC 2822 message and return it base64url-encoded for the API."""
    msg = MIMEText(body)
    msg["To"] = to
    msg["Subject"] = subject
    if sender:
        msg["From"] = sender
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


class GmailService(ABC):
    @abstractmethod
    async def list_inbox(self, user_id: str, max_results: int = 20) -> dict: ...

    @abstractmethod
    async def search(self, user_id: str, query: str, max_results: int = 20) -> dict: ...

    @abstractmethod
    async def send(self, user_id: str, to: str, subject: str, body: str) -> dict: ...

    @abstractmethod
    async def draft_reply(self, user_id: str, message_id: str, body: str) -> dict: ...


class GmailApiService(GmailService):
    def __init__(self, store: CredentialStore | None = None) -> None:
        self.store = store or get_credential_store()
        self.max_results = get_settings().gmail_max_results

    async def _client(self, user_id: str):
        """Load creds, refresh if needed, return an authed Gmail client.

        Runs the blocking google client construction in a thread.
        """
        import asyncio

        token = await self.store.load(user_id, "gmail")
        if token is None:
            raise NotConnected()

        def _build():
            from google.auth.transport.requests import Request  # lazy
            from googleapiclient.discovery import build  # lazy

            creds = credentials_from_dict(token)
            refreshed = None
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                refreshed = creds_to_dict(creds)
            service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            return service, refreshed

        service, refreshed = await asyncio.to_thread(_build)
        if refreshed:
            await self.store.save(user_id, "gmail", refreshed)
        return service

    async def _run(self, fn):
        """Execute a blocking Gmail API call, mapping errors."""
        import asyncio

        from googleapiclient.errors import HttpError  # lazy

        try:
            return await asyncio.to_thread(fn)
        except HttpError as exc:
            status = getattr(exc, "status_code", None) or exc.resp.status
            if status in (429, 403):
                raise GmailError("rate_limited", "Gmail rate limit or quota exceeded")
            if status == 401:
                raise GmailError("unauthorized", "Gmail authorization expired; reconnect")
            raise GmailError("api_error", f"Gmail API error {status}")
        except GmailError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GmailError("unexpected", str(exc))

    async def list_inbox(self, user_id: str, max_results: int = 20) -> dict:
        service = await self._client(user_id)
        n = min(max_results, self.max_results)

        def _call():
            listing = service.users().messages().list(
                userId="me", labelIds=["INBOX"], maxResults=n).execute()
            out = []
            for ref in listing.get("messages", []):
                msg = service.users().messages().get(
                    userId="me", id=ref["id"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]).execute()
                out.append(_summarize(msg))
            return {"messages": out, "count": len(out)}

        return await self._run(_call)

    async def search(self, user_id: str, query: str, max_results: int = 20) -> dict:
        service = await self._client(user_id)
        n = min(max_results, self.max_results)

        def _call():
            listing = service.users().messages().list(
                userId="me", q=query, maxResults=n).execute()
            out = []
            for ref in listing.get("messages", []):
                msg = service.users().messages().get(
                    userId="me", id=ref["id"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]).execute()
                out.append(_summarize(msg))
            return {"query": query, "messages": out, "count": len(out)}

        return await self._run(_call)

    async def send(self, user_id: str, to: str, subject: str, body: str) -> dict:
        service = await self._client(user_id)
        raw = build_raw_message(to, subject, body)

        def _call():
            sent = service.users().messages().send(
                userId="me", body={"raw": raw}).execute()
            return {"sent": True, "id": sent.get("id"), "to": to}

        return await self._run(_call)

    async def draft_reply(self, user_id: str, message_id: str, body: str) -> dict:
        service = await self._client(user_id)

        def _call():
            original = service.users().messages().get(
                userId="me", id=message_id, format="metadata",
                metadataHeaders=["From", "Subject", "Message-ID"]).execute()
            headers = {h["name"].lower(): h["value"]
                       for h in original.get("payload", {}).get("headers", [])}
            to = headers.get("from", "")
            subject = headers.get("subject", "")
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"
            raw = build_raw_message(to, subject, body,
                                    in_reply_to=headers.get("message-id"))
            draft = service.users().drafts().create(
                userId="me",
                body={"message": {"raw": raw, "threadId": original.get("threadId")}}
            ).execute()
            return {"draft_id": draft.get("id"), "to": to, "subject": subject}

        return await self._run(_call)


def _summarize(msg: dict) -> dict:
    headers = {h["name"].lower(): h["value"]
               for h in msg.get("payload", {}).get("headers", [])}
    return {
        "id": msg.get("id"),
        "thread_id": msg.get("threadId"),
        "from": headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "snippet": msg.get("snippet", ""),
    }


def get_gmail_service() -> GmailService:
    return GmailApiService()
