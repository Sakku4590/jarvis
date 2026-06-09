"""Plan executor.

Walks a validated plan in its topological `order`, and for each step selects a
tool, resolves inputs that reference earlier outputs, and runs the tool through
the pipeline. Two production behaviors worth noting:

  - cross-step data flow: an input value of "$s1.output" is replaced with the
    data returned by step s1, so a summarize step can consume a search step.
  - failure containment: if a step errors or is held for approval, every step
    that (transitively) depends on it is skipped rather than run on missing
    inputs. The run completes with a full, honest per-step report.
"""

from pydantic import BaseModel

from app.core.logging import get_logger
from app.planner.schemas import Plan
from app.tools.pipeline import ToolPipeline
from app.tools.schemas import ToolContext, ToolResult, ToolStatus
from app.tools.selector import ToolSelector

log = get_logger(__name__)


class StepResult(BaseModel):
    step_id: str
    capability: str
    tool: str | None = None
    status: str
    ok: bool
    data: dict | None = None
    error: dict | None = None


class PlanExecutor:
    def __init__(self, selector: ToolSelector, pipeline: ToolPipeline) -> None:
        self.selector = selector
        self.pipeline = pipeline

    async def run(self, plan: Plan, ctx: ToolContext) -> list[StepResult]:
        outputs: dict[str, dict | None] = {}
        blocked: set[str] = set()
        results: list[StepResult] = []

        for step_id in plan.order:
            step = plan.step(step_id)
            if step is None:
                continue

            # Skip if any dependency failed / is unfulfilled.
            failed_deps = [d for d in step.depends_on if d in blocked]
            if failed_deps:
                blocked.add(step_id)
                results.append(StepResult(
                    step_id=step_id, capability=step.capability, status="skipped",
                    ok=False, error={"code": "dependency_unmet",
                                     "message": f"depends on {failed_deps}"}))
                continue

            tool = await self.selector.select(step.capability, step.inputs)
            if tool is None:
                blocked.add(step_id)
                results.append(StepResult(
                    step_id=step_id, capability=step.capability, status="error",
                    ok=False, error={"code": "no_tool",
                                     "message": f"no tool for capability '{step.capability}'"}))
                continue

            resolved = self._resolve_inputs(step.inputs, outputs)
            result: ToolResult = await self.pipeline.execute(tool, resolved, ctx)

            outputs[step_id] = result.data
            if not result.ok:
                # A held-for-approval or errored step blocks its dependents.
                blocked.add(step_id)

            results.append(StepResult(
                step_id=step_id, capability=step.capability, tool=tool.name,
                status=result.status.value, ok=result.ok, data=result.data,
                error=(result.error.model_dump() if result.error else None)))

        log.info("supervisor.execute", steps=len(results),
                 blocked=len(blocked), plan_goal=plan.goal[:80])
        return results

    @staticmethod
    def _resolve_inputs(inputs: dict, outputs: dict[str, dict | None]) -> dict:
        """Replace "$<step_id>.output" / "$<step_id>" references with prior data."""
        resolved: dict = {}
        for key, value in inputs.items():
            if isinstance(value, str) and value.startswith("$"):
                ref = value[1:].split(".", 1)[0]
                resolved[key] = outputs.get(ref)
            else:
                resolved[key] = value
        return resolved
