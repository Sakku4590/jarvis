"""Tool selection.

Given a capability and a step's inputs, pick which tool to run. The strategy is
deterministic first, LLM only as a last resort:

  1. explicit action: inputs has "action" and "<capability>.<action>" exists
  2. single tool: the capability has exactly one tool
  3. ambiguous: ask the LLM to choose among the capability's tools (falls back
     to the first registered tool if no LLM is configured)

Keeping selection mostly deterministic means most calls cost nothing extra and
behave predictably; the LLM only arbitrates genuine ambiguity.
"""

import json

from app.core.llm import LLMClient
from app.core.logging import get_logger
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolSpec

log = get_logger(__name__)

_SELECT_SYSTEM = """Choose the single best tool for the task. Reply with a JSON \
object {"tool": "<exact tool name>"} using one of the names provided."""


class ToolSelector:
    def __init__(self, registry: ToolRegistry, llm: LLMClient | None = None) -> None:
        self.registry = registry
        self.llm = llm

    async def select(self, capability: str, inputs: dict) -> ToolSpec | None:
        action = inputs.get("action")
        if isinstance(action, str):
            exact = self.registry.get(f"{capability}.{action}")
            if exact is not None:
                return exact

        tools = self.registry.by_capability(capability)
        if not tools:
            return None
        if len(tools) == 1:
            return tools[0]

        if self.llm is not None:
            chosen = await self._llm_pick(tools, inputs)
            if chosen is not None:
                return chosen

        log.info("tool.select_fallback", capability=capability, picked=tools[0].name)
        return tools[0]

    async def _llm_pick(self, tools: list[ToolSpec], inputs: dict) -> ToolSpec | None:
        catalog = "\n".join(f"- {t.name}: {t.description}" for t in tools)
        user = json.dumps({"task_inputs": inputs, "tools": catalog})
        try:
            data = await self.llm.complete_json(_SELECT_SYSTEM, user)
            return self.registry.get(data.get("tool", ""))
        except Exception as exc:  # noqa: BLE001
            log.warning("tool.select_llm_failed", error=str(exc))
            return None
