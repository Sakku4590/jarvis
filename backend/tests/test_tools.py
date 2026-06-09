"""Tests for the tool layer: pipeline stages and tool selection."""

import pytest
from pydantic import BaseModel

from app.tools.builtin import make_default_registry
from app.tools.pipeline import ToolPipeline
from app.tools.schemas import RiskClass, ToolContext, ToolSpec, ToolStatus
from app.tools.selector import ToolSelector


class DoubleArgs(BaseModel):
    x: int


async def _double(args: DoubleArgs, ctx: ToolContext) -> dict:
    return {"y": args.x * 2}


def _tool(**over) -> ToolSpec:
    base = dict(name="math.double", capability="math",
                description="double x", args_schema=DoubleArgs, handler=_double,
                risk_class=RiskClass.READ, requires_approval=False)
    base.update(over)
    return ToolSpec(**base)


CTX = ToolContext(user_id="u1")


async def test_success_envelope():
    res = await ToolPipeline().execute(_tool(), {"x": 3}, CTX)
    assert res.ok and res.status is ToolStatus.SUCCESS
    assert res.data == {"y": 6}
    assert res.meta["tool"] == "math.double" and "duration_ms" in res.meta


async def test_invalid_args():
    res = await ToolPipeline().execute(_tool(), {"x": "not-an-int"}, CTX)
    assert not res.ok and res.status is ToolStatus.INVALID_ARGS


async def test_risk_gate_holds_then_clears():
    risky = _tool(risk_class=RiskClass.DESTRUCTIVE, requires_approval=True)
    held = await ToolPipeline().execute(risky, {"x": 1}, ToolContext(user_id="u1"))
    assert held.status is ToolStatus.PENDING_APPROVAL and not held.ok

    cleared = await ToolPipeline().execute(
        risky, {"x": 1}, ToolContext(user_id="u1", approved=True))
    assert cleared.ok and cleared.status is ToolStatus.SUCCESS


async def test_not_permitted_when_capability_disabled():
    ctx = ToolContext(user_id="u1", deps={"disabled_capabilities": ["math"]})
    res = await ToolPipeline().execute(_tool(), {"x": 1}, ctx)
    assert res.status is ToolStatus.NOT_PERMITTED


async def test_handler_exception_becomes_error_envelope():
    async def boom(args, ctx):
        raise RuntimeError("kaboom")

    res = await ToolPipeline().execute(_tool(handler=boom), {"x": 1}, CTX)
    assert not res.ok and res.status is ToolStatus.ERROR
    assert "kaboom" in res.error.message


async def test_selector_prefers_action_key():
    reg = make_default_registry()
    sel = ToolSelector(reg)  # no LLM
    tool = await sel.select("file", {"action": "read"})
    assert tool is not None and tool.name == "file.read"


async def test_selector_single_tool_shortcut():
    reg = make_default_registry()
    sel = ToolSelector(reg)
    tool = await sel.select("calendar", {})  # calendar has one tool
    assert tool is not None and tool.name == "calendar.create"


async def test_selector_unknown_capability_returns_none():
    sel = ToolSelector(make_default_registry())
    assert await sel.select("teleport", {}) is None
