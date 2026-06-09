"""In-memory activity store for the dashboard.

Keeps recent tool calls and task runs in capped ring buffers so the dashboard
can show live activity without a database. RecordingAuditSink plugs into the
tool pipeline: it logs (as before) and also records each call here.

This is process-local and ephemeral by design; durable history belongs in the
tool_calls / tasks tables, which a later phase can back this with.
"""

import time
from collections import deque

from app.tools.pipeline import AuditSink, LogAuditSink


class ActivityStore:
    def __init__(self, maxlen: int = 250) -> None:
        self.tools: deque[dict] = deque(maxlen=maxlen)
        self.tasks: deque[dict] = deque(maxlen=maxlen)

    def record_tool(self, entry: dict) -> None:
        self.tools.appendleft(entry)

    def record_task(self, entry: dict) -> None:
        self.tasks.appendleft(entry)

    def recent_tools(self, limit: int = 50) -> list[dict]:
        return list(self.tools)[:limit]

    def recent_tasks(self, limit: int = 50) -> list[dict]:
        return list(self.tasks)[:limit]


_store = ActivityStore()


def get_activity_store() -> ActivityStore:
    return _store


class RecordingAuditSink(AuditSink):
    """Logs every tool call (like LogAuditSink) and records it for the dashboard."""

    def __init__(self) -> None:
        self._log = LogAuditSink()
        self._store = get_activity_store()

    async def record(self, tool, raw_args, ctx, result) -> None:
        await self._log.record(tool, raw_args, ctx, result)
        self._store.record_tool({
            "time": time.time(),
            "tool": tool.name,
            "capability": tool.capability,
            "risk": tool.risk_class.value,
            "status": result.status.value,
            "ok": result.ok,
            "user_id": ctx.user_id,
            "duration_ms": result.meta.get("duration_ms"),
        })
