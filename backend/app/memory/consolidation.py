"""Memory consolidation (write/update path).

Two steps, kept as injectable objects so tests can swap in fakes:

  FactExtractor.extract(messages)  -> candidate facts (LLM)
  FactResolver.resolve(fact, ...)  -> insert | skip | supersede decision

Resolution is the interesting part. For each candidate we pull its nearest
existing neighbors and decide:
  - no close neighbor (distance > relate)        -> INSERT
  - a near-identical neighbor (distance <= dup)  -> SKIP (and touch it)
  - a related-but-different neighbor in between   -> ask the LLM whether the
        new fact updates the old one (SUPERSEDE) or is genuinely new (INSERT)
A deterministic fallback covers the middle band when no LLM is configured, so
the pipeline always runs.
"""

import json

from app.core.config import get_settings
from app.core.llm import LLMClient
from app.core.logging import get_logger
from app.memory.schemas import ExtractedFact, MemoryKind, ResolutionDecision
from app.memory.store import BaseMemoryStore

log = get_logger(__name__)

_EXTRACT_SYSTEM = """You extract durable, long-term facts about a user from a \
conversation. Keep only things worth remembering for weeks or months: stable \
preferences, people and relationships, ongoing projects, persistent facts, and \
how the user likes tasks done. Ignore one-off or transient details.

Reply with a single JSON object of the form:
{"facts": [{"kind": "...", "subject": "...", "content": "...", "confidence": 0.0-1.0}]}
where "kind" is one of: preference, person, project, fact, procedure.
"content" is a concise standalone statement. "subject" is the entity it is \
about (a person name, project name, or topic), or null. Return an empty list \
if nothing is worth storing."""

_RESOLVE_SYSTEM = """You decide how a new candidate fact relates to existing \
stored facts about a user. Reply with a single JSON object:
{"action": "insert|skip|supersede", "target_index": <int or null>, "reason": "..."}
- "skip": the new fact says the same thing as an existing one.
- "supersede": the new fact updates or contradicts an existing one \
(target_index points at it).
- "insert": the new fact is genuinely new.
Choose target_index from the numbered existing facts when superseding or \
skipping."""


class FactExtractor:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    async def extract(self, messages: list[dict]) -> list[ExtractedFact]:
        transcript = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages
        )
        data = await self.llm.complete_json(_EXTRACT_SYSTEM, transcript)
        facts: list[ExtractedFact] = []
        for raw in data.get("facts", []):
            try:
                facts.append(ExtractedFact(**raw))
            except Exception as exc:  # noqa: BLE001
                log.warning("memory.extract_bad_fact", raw=raw, error=str(exc))
        log.info("memory.extract", count=len(facts))
        return facts


class FactResolver:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    async def resolve(
        self, user_id: str, fact: ExtractedFact, store: BaseMemoryStore
    ) -> ResolutionDecision:
        s = get_settings()
        neighbors = await store.semantic_search(user_id, fact.content, k=3)

        # NOTE: distance can be exactly 0.0 (a perfect match), which is falsy,
        # so compare against None explicitly rather than using `or`.
        best_distance = None
        if neighbors:
            best_distance = neighbors[0].distance
            best_distance = 1.0 if best_distance is None else best_distance

        if not neighbors or best_distance > s.memory_relate_distance:
            return ResolutionDecision(fact=fact, action="insert", reason="no related fact")

        best = neighbors[0]
        if best_distance <= s.memory_dup_distance:
            return ResolutionDecision(
                fact=fact, action="skip", target_id=best.id, reason="near-duplicate"
            )

        # Related but not identical: let the LLM judge, fall back to a heuristic.
        try:
            return await self._judge(fact, neighbors)
        except Exception as exc:  # noqa: BLE001
            log.warning("memory.resolve_llm_failed", error=str(exc))
            same_subject = best.subject and best.subject == fact.subject
            if same_subject and best.kind == fact.kind:
                return ResolutionDecision(
                    fact=fact, action="supersede", target_id=best.id,
                    reason="heuristic: same subject/kind, updated content",
                )
            return ResolutionDecision(fact=fact, action="insert", reason="heuristic: distinct")

    async def _judge(
        self, fact: ExtractedFact, neighbors: list
    ) -> ResolutionDecision:
        listing = "\n".join(
            f"{i}. [{n.kind.value}/{n.subject or ''}] {n.content}"
            for i, n in enumerate(neighbors)
        )
        user = json.dumps(
            {
                "new_fact": {
                    "kind": fact.kind.value,
                    "subject": fact.subject,
                    "content": fact.content,
                },
                "existing_facts": listing,
            }
        )
        data = await self.llm.complete_json(_RESOLVE_SYSTEM, user)
        action = data.get("action", "insert")
        idx = data.get("target_index")
        target_id = None
        if isinstance(idx, int) and 0 <= idx < len(neighbors):
            target_id = neighbors[idx].id
        if action in {"skip", "supersede"} and target_id is None:
            action = "insert"  # cannot act on a missing target
        return ResolutionDecision(
            fact=fact, action=action, target_id=target_id, reason=data.get("reason")
        )
