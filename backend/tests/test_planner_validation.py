"""Unit tests for plan validation (pure, no LLM)."""

from app.planner.capabilities import default_registry
from app.planner.schemas import Plan, PlanStatus, PlanStep
from app.planner.validation import validate_plan

REG = default_registry()


def _step(sid, cap="file", deps=None):
    return PlanStep(id=sid, description=sid, capability=cap, depends_on=deps or [])


def test_linear_plan_is_ready_and_ordered():
    plan = Plan(goal="g", steps=[
        _step("s1"),
        _step("s2", deps=["s1"]),
        _step("s3", cap="email", deps=["s2"]),
    ])
    out = validate_plan(plan, REG)
    assert out.status is PlanStatus.READY
    assert out.errors == []
    assert out.order == ["s1", "s2", "s3"]


def test_branching_plan_orders_dependencies_first():
    plan = Plan(goal="g", steps=[
        _step("s4", deps=["s2", "s3"]),
        _step("s1"),
        _step("s2", deps=["s1"]),
        _step("s3", deps=["s1"]),
    ])
    out = validate_plan(plan, REG)
    assert out.status is PlanStatus.READY
    assert out.order[0] == "s1"
    assert out.order[-1] == "s4"
    # s2 and s3 come after s1 and before s4
    assert out.order.index("s2") > 0 and out.order.index("s3") > 0


def test_cycle_is_invalid():
    plan = Plan(goal="g", steps=[
        _step("s1", deps=["s2"]),
        _step("s2", deps=["s1"]),
    ])
    out = validate_plan(plan, REG)
    assert out.status is PlanStatus.INVALID
    assert any("cycle" in e for e in out.errors)


def test_unknown_dependency_is_invalid():
    plan = Plan(goal="g", steps=[_step("s1", deps=["sX"])])
    out = validate_plan(plan, REG)
    assert out.status is PlanStatus.INVALID
    assert any("unknown step" in e for e in out.errors)


def test_unknown_capability_is_invalid():
    plan = Plan(goal="g", steps=[_step("s1", cap="teleport")])
    out = validate_plan(plan, REG)
    assert out.status is PlanStatus.INVALID
    assert any("unknown capability" in e for e in out.errors)


def test_duplicate_id_is_invalid():
    plan = Plan(goal="g", steps=[_step("s1"), _step("s1", cap="email")])
    out = validate_plan(plan, REG)
    assert out.status is PlanStatus.INVALID
    assert any("duplicate step id" in e for e in out.errors)


def test_self_dependency_is_invalid():
    plan = Plan(goal="g", steps=[_step("s1", deps=["s1"])])
    out = validate_plan(plan, REG)
    assert out.status is PlanStatus.INVALID
    assert any("itself" in e for e in out.errors)
