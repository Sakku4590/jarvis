"""Tool execution pipeline.

Every tool call goes through here; nothing calls a handler directly. The stages
mirror the architecture spec:

    validate args -> permission -> risk gate -> execute (timeout + retry)
    -> audit -> normalized ToolResult

The risk gate is the safety backbone: a tool flagged requires_approval returns
PENDING_APPROVAL instead of running unless the context carries an approval. The
full human-in-the-loop resume (LangGraph interrupt + approvals table) layers on
top of this gate in a later phase; the gate itself lives here.
"""

import asyncio
import time
from abc import ABC, abstractmethod

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.tools.schemas import (
    ToolContext,
    ToolResult,
    ToolSpec,
    ToolStatus,
)

log = get_logger(__name__)


class AuditSink(ABC):
    @abstractmethod
    async def record(
        self, tool: ToolSpec, raw_args: dict, ctx: ToolContext, result: ToolResult
    ) -> None: ...


class LogAuditSink(AuditSink):
    """Default sink: structured log line per tool call. No database needed."""

    async def record(self, tool, raw_args, ctx, result) -> None:
        log.info(
            "tool.call",
            tool=tool.name,
            capability=tool.capability,
            risk=tool.risk_class.value,
            status=result.status.value,
            ok=result.ok,
            user_id=ctx.user_id,
            duration_ms=result.meta.get("duration_ms"),
        )


def get_audit_sink() -> AuditSink:
    # Records tool calls into the in-memory activity store (for the dashboard)
    # in addition to logging. Swap for a Postgres-backed sink (tool_calls table)
    # when durable audit persistence is needed.
    from app.observability.activity import RecordingAuditSink

    return RecordingAuditSink()


class ToolPipeline:
    def __init__(self, audit: AuditSink | None = None) -> None:
        self.audit = audit or get_audit_sink()

    async def execute(
        self, tool: ToolSpec, raw_args: dict, ctx: ToolContext
    ) -> ToolResult:
        settings = get_settings()
        started = time.perf_counter()
        meta = {"tool": tool.name}

        def finish(result: ToolResult) -> ToolResult:
            result.meta = {**meta, **result.meta,
                           "duration_ms": round((time.perf_counter() - started) * 1000, 2)}
            return result

        # 1. validate args
        try:
            args = tool.args_schema(**raw_args)
        except ValidationError as exc:
            result = finish(ToolResult.failure(
                ToolStatus.INVALID_ARGS, "invalid_args", str(exc), meta))
            await self.audit.record(tool, raw_args, ctx, result)
            return result

        # 2. permission (placeholder: single-user trusts itself; real checks for
        #    connected integrations / scopes go here)
        if not self._permitted(tool, ctx):
            result = finish(ToolResult.failure(
                ToolStatus.NOT_PERMITTED, "not_permitted",
                f"capability '{tool.capability}' is not available", meta))
            await self.audit.record(tool, raw_args, ctx, result)
            return result

        # 3. risk gate
        if (
            tool.requires_approval
            and settings.risky_actions_need_approval
            and not ctx.approved
        ):
            result = finish(ToolResult.failure(
                ToolStatus.PENDING_APPROVAL, "pending_approval",
                f"{tool.name} ({tool.risk_class.value}) needs approval before running",
                meta))
            await self.audit.record(tool, raw_args, ctx, result)
            return result

        # 4. execute with timeout + bounded retry
        attempts = max(1, settings.tool_max_attempts)
        last_error = ""
        for attempt in range(1, attempts + 1):
            try:
                data = await asyncio.wait_for(
                    tool.handler(args, ctx), timeout=settings.tool_timeout_seconds
                )
                result = finish(ToolResult.success(data, {"attempts": attempt}))
                await self.audit.record(tool, raw_args, ctx, result)
                return result
            except asyncio.TimeoutError:
                last_error = f"timed out after {settings.tool_timeout_seconds}s"
            except Exception as exc:  # noqa: BLE001 - normalized into the envelope
                last_error = str(exc)
                log.warning("tool.exec_failed", tool=tool.name, attempt=attempt,
                            error=last_error)

        result = finish(ToolResult.failure(
            ToolStatus.ERROR, "execution_error", last_error, {"attempts": attempts}))
        await self.audit.record(tool, raw_args, ctx, result)
        return result

    @staticmethod
    def _permitted(tool: ToolSpec, ctx: ToolContext) -> bool:
        disabled = set(ctx.deps.get("disabled_capabilities", []))
        return tool.capability not in disabled
