"""Memory Agent (LangGraph).

A StateGraph with a conditional entry that runs one of two flows:

    START ─(retrieve)──▶ retrieve ───────────────────────▶ END
          └(consolidate)▶ extract ─▶ resolve ─▶ store ────▶ END

Nodes close over injected dependencies (store, extractor, resolver) so the same
graph runs against the real Postgres+Chroma store in production and an in-memory
fake in tests. The agent is invoked as a step by the wider system, not chosen by
a router, matching the cross-cutting role in the architecture spec.
"""

from langgraph.graph import END, START, StateGraph

from app.core.logging import get_logger
from app.memory.consolidation import FactExtractor, FactResolver
from app.memory.retrieval import retrieve_memories
from app.memory.schemas import ExtractedFact, ResolutionDecision
from app.memory.state import MemoryState
from app.memory.store import BaseMemoryStore, get_memory_store

log = get_logger(__name__)


def build_memory_graph(
    store: BaseMemoryStore,
    extractor: FactExtractor,
    resolver: FactResolver,
):
    """Compile the Memory Agent graph with the given dependencies."""

    # --- retrieve flow ---
    async def retrieve_node(state: MemoryState) -> dict:
        ctx = await retrieve_memories(store, state["user_id"], state.get("query", ""))
        return {
            "retrieved": [m.model_dump(mode="json") for m in ctx.memories],
            "memory_block": ctx.memory_block,
        }

    # --- consolidate flow ---
    async def extract_node(state: MemoryState) -> dict:
        facts = await extractor.extract(state.get("messages", []))
        return {"extracted": [f.model_dump(mode="json") for f in facts]}

    async def resolve_node(state: MemoryState) -> dict:
        decisions: list[ResolutionDecision] = []
        for raw in state.get("extracted", []):
            fact = ExtractedFact(**raw)
            decisions.append(await resolver.resolve(state["user_id"], fact, store))
        return {"decisions": [d.model_dump(mode="json") for d in decisions]}

    async def store_node(state: MemoryState) -> dict:
        user_id = state["user_id"]
        src = state.get("source_message_id")
        written: list[str] = []
        for raw in state.get("decisions", []):
            decision = ResolutionDecision(**raw)
            if decision.action == "insert":
                written.append(await store.add_fact(user_id, decision.fact, src))
            elif decision.action == "supersede" and decision.target_id:
                written.append(
                    await store.supersede_fact(
                        user_id, decision.target_id, decision.fact, src
                    )
                )
            elif decision.action == "skip" and decision.target_id:
                await store.touch_facts([decision.target_id])
        log.info("memory.store", user_id=user_id, written=len(written))
        return {"written": written}

    def route(state: MemoryState) -> str:
        return state.get("mode", "retrieve")

    g = StateGraph(MemoryState)
    g.add_node("retrieve", retrieve_node)
    g.add_node("extract", extract_node)
    g.add_node("resolve", resolve_node)
    g.add_node("store", store_node)

    g.add_conditional_edges(
        START,
        route,
        {"retrieve": "retrieve", "consolidate": "extract"},
    )
    g.add_edge("retrieve", END)
    g.add_edge("extract", "resolve")
    g.add_edge("resolve", "store")
    g.add_edge("store", END)

    return g.compile()


class MemoryAgent:
    """Thin convenience wrapper over the compiled graph."""

    def __init__(
        self,
        store: BaseMemoryStore | None = None,
        extractor: FactExtractor | None = None,
        resolver: FactResolver | None = None,
    ) -> None:
        self.store = store or get_memory_store()
        self.graph = build_memory_graph(
            self.store,
            extractor or FactExtractor(),
            resolver or FactResolver(),
        )

    async def aretrieve(self, user_id: str, query: str) -> dict:
        return await self.graph.ainvoke(
            {"mode": "retrieve", "user_id": user_id, "query": query}
        )

    async def aconsolidate(
        self,
        user_id: str,
        messages: list[dict],
        source_message_id: str | None = None,
    ) -> dict:
        return await self.graph.ainvoke(
            {
                "mode": "consolidate",
                "user_id": user_id,
                "messages": messages,
                "source_message_id": source_message_id,
            }
        )


def get_memory_agent() -> MemoryAgent:
    return MemoryAgent()
