"""Plan validation.

An LLM emits a plausible-looking plan; this module decides whether it is
actually executable. It is pure (no LLM, no IO), which makes it fully testable
and is exactly where the planner's correctness lives.

Checks performed:
  1. step ids are unique and non-empty
  2. every depends_on references an existing step
  3. every capability exists in the registry
  4. the dependency graph is acyclic
And, when valid, it computes a topological execution order with Kahn's
algorithm so an executor can run steps in a safe sequence.
"""

from app.planner.capabilities import CapabilityRegistry
from app.planner.schemas import Plan, PlanStatus


def validate_plan(plan: Plan, registry: CapabilityRegistry) -> Plan:
    """Return the plan with `errors`, `order`, and `status` populated."""
    errors: list[str] = []
    ids = [s.id for s in plan.steps]

    # 1. unique, non-empty ids
    seen: set[str] = set()
    for sid in ids:
        if not sid:
            errors.append("a step has an empty id")
        elif sid in seen:
            errors.append(f"duplicate step id: {sid}")
        seen.add(sid)

    id_set = set(ids)

    # 2 + 3. references and capabilities
    for s in plan.steps:
        for dep in s.depends_on:
            if dep not in id_set:
                errors.append(f"step {s.id} depends on unknown step {dep}")
            if dep == s.id:
                errors.append(f"step {s.id} depends on itself")
        if not registry.has(s.capability):
            errors.append(f"step {s.id} uses unknown capability '{s.capability}'")

    # 4 + order. Topological sort over valid edges only.
    order, cyclic = _topological_order(plan)
    if cyclic:
        errors.append(f"dependency cycle among steps: {sorted(cyclic)}")

    plan.errors = errors
    plan.order = order
    plan.status = PlanStatus.READY if not errors else PlanStatus.INVALID
    return plan


def _topological_order(plan: Plan) -> tuple[list[str], set[str]]:
    """Kahn's algorithm. Returns (order, nodes_left_in_a_cycle).

    Uses only dependency edges that point at real steps, so a missing reference
    is reported separately rather than corrupting the ordering.
    """
    id_set = {s.id for s in plan.steps}
    # dependents[d] = steps that wait on d
    dependents: dict[str, list[str]] = {s.id: [] for s in plan.steps}
    indegree: dict[str, int] = {s.id: 0 for s in plan.steps}

    for s in plan.steps:
        valid_deps = [d for d in set(s.depends_on) if d in id_set and d != s.id]
        indegree[s.id] = len(valid_deps)
        for d in valid_deps:
            dependents[d].append(s.id)

    queue = sorted([n for n, deg in indegree.items() if deg == 0])
    order: list[str] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for nxt in dependents[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
        queue.sort()  # stable, deterministic ordering for equal-depth steps

    cyclic = {n for n in id_set if n not in order}
    return order, cyclic
