"""Memory retrieval (read path).

Runs two queries and merges them: semantic neighbors from Chroma (what is
related to this message) and the most recent current facts from Postgres (what
is freshly true). Results are deduped, ranked, and capped to a character budget
so the injected memory block never crowds out the actual conversation.
"""

from app.core.config import get_settings
from app.core.logging import get_logger
from app.memory.schemas import RetrievedContext, RetrievedMemory
from app.memory.store import BaseMemoryStore

log = get_logger(__name__)


async def retrieve_memories(
    store: BaseMemoryStore,
    user_id: str,
    query: str,
    *,
    top_k: int | None = None,
    recent_k: int | None = None,
    char_budget: int | None = None,
    touch: bool = True,
) -> RetrievedContext:
    s = get_settings()
    top_k = top_k or s.memory_top_k
    recent_k = recent_k or s.memory_recent_k
    char_budget = char_budget or s.memory_char_budget

    semantic = await store.semantic_search(user_id, query, top_k) if query else []
    recent = await store.recent_facts(user_id, recent_k)

    merged = _merge(semantic, recent)
    budgeted = _apply_budget(merged, char_budget)

    if touch and budgeted:
        await store.touch_facts([m.id for m in budgeted])

    log.info(
        "memory.retrieve",
        user_id=user_id,
        semantic=len(semantic),
        recent=len(recent),
        returned=len(budgeted),
    )
    return RetrievedContext(memories=budgeted, memory_block=_format_block(budgeted))


def _merge(
    semantic: list[RetrievedMemory], recent: list[RetrievedMemory]
) -> list[RetrievedMemory]:
    """Dedup by id, keeping the semantic hit (it carries a distance score).
    Semantic hits rank first by closeness, recent hits fill in after."""
    seen: dict[str, RetrievedMemory] = {}
    for m in semantic:
        seen[m.id] = m
    for m in recent:
        seen.setdefault(m.id, m)

    def sort_key(m: RetrievedMemory) -> tuple[int, float]:
        # Semantic (distance set) first, ordered by distance; recent after.
        if m.distance is not None:
            return (0, m.distance)
        return (1, 0.0)

    return sorted(seen.values(), key=sort_key)


def _apply_budget(
    memories: list[RetrievedMemory], char_budget: int
) -> list[RetrievedMemory]:
    out: list[RetrievedMemory] = []
    used = 0
    for m in memories:
        cost = len(m.content) + 16  # rough overhead for the formatted line
        if used + cost > char_budget:
            break
        out.append(m)
        used += cost
    return out


def _format_block(memories: list[RetrievedMemory]) -> str:
    """Render a compact 'what I know about the user' block for prompt injection."""
    if not memories:
        return ""
    lines = ["What I remember about the user:"]
    for m in memories:
        prefix = f"[{m.kind.value}" + (f"/{m.subject}" if m.subject else "") + "]"
        lines.append(f"- {prefix} {m.content}")
    return "\n".join(lines)
