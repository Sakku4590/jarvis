"""Intent classification (the supervisor's routing logic).

Decides which path a message takes:
  - chat:   answerable directly, no tools or external actions
  - single: exactly one capability/action is needed (the fast path)
  - plan:   multi-step or cross-capability work (hand to the Planner Agent)

This is the fast-path / agent-path split from the architecture: trivial
requests should not pay for full planning. LLM-backed with a safe heuristic
fallback (default to planning) so a model hiccup never drops a request.
"""

from typing import Literal

from pydantic import BaseModel

from app.core.llm import LLMClient
from app.core.logging import get_logger

log = get_logger(__name__)

Route = Literal["chat", "single", "plan"]


class ClassifyResult(BaseModel):
    route: Route = "plan"
    capability: str | None = None
    reason: str | None = None


def _system(capabilities: list[str]) -> str:
    return f"""You route a user's message to one of three paths.

Capabilities available: {", ".join(capabilities)}

- "chat": the message can be answered directly with no tools or external \
actions (a question, a definition, smalltalk).
- "single": the message needs exactly ONE capability and one action (e.g. \
"play some jazz" -> music). Set "capability" to the one needed.
- "plan": the message needs multiple steps or more than one capability (e.g. \
"find the contract, summarize it, and email John").

Reply with a single JSON object:
{{"route": "chat|single|plan", "capability": "<one capability or null>", \
"reason": "..."}}"""


class IntentClassifier:
    def __init__(self, capabilities: list[str], llm: LLMClient | None = None) -> None:
        self.capabilities = capabilities
        self.llm = llm or LLMClient()

    async def classify(self, message: str, memory_block: str = "") -> ClassifyResult:
        user = message if not memory_block else f"{memory_block}\n\nMessage: {message}"
        try:
            data = await self.llm.complete_json(self._system_cached(), user)
            result = ClassifyResult(**data)
            # A "single" route with an unknown capability is not actionable.
            if result.route == "single" and result.capability not in self.capabilities:
                result.route = "plan"
            log.info("supervisor.classify", route=result.route,
                     capability=result.capability)
            return result
        except Exception as exc:  # noqa: BLE001
            log.warning("supervisor.classify_failed", error=str(exc))
            return ClassifyResult(route="plan", reason="classifier fallback")

    def _system_cached(self) -> str:
        return _system(self.capabilities)
