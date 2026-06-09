"""End-to-end Memory Agent tests.

Drives the real LangGraph graph, real retrieval, and real consolidation logic.
Only the external boundaries are faked: the Postgres+Chroma store (an in-memory
implementation of BaseMemoryStore) and the LLM (canned JSON keyed off the
system prompt). This proves the graph wiring and the insert / skip / supersede
decision paths without needing any external service.
"""

import re
import uuid

import pytest

from app.memory.agent import build_memory_graph
from app.memory.consolidation import FactExtractor, FactResolver
from app.memory.schemas import ExtractedFact, MemoryKind, RetrievedMemory
from app.memory.store import BaseMemoryStore


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


class InMemoryStore(BaseMemoryStore):
    """A dependency-free BaseMemoryStore for tests. Distance is 1 - token
    overlap, which is enough to drive the real threshold logic."""

    def __init__(self) -> None:
        self.facts: dict[str, dict] = {}  # id -> {fact, valid}

    async def add_fact(self, user_id, fact, source_message_id=None) -> str:
        fid = str(uuid.uuid4())
        self.facts[fid] = {"fact": fact, "valid": True, "user_id": user_id}
        return fid

    async def supersede_fact(self, user_id, old_id, new_fact, source_message_id=None) -> str:
        if old_id in self.facts:
            self.facts[old_id]["valid"] = False
        return await self.add_fact(user_id, new_fact, source_message_id)

    async def semantic_search(self, user_id, query, k) -> list[RetrievedMemory]:
        q = _tokens(query)
        scored = []
        for fid, rec in self.facts.items():
            if not rec["valid"] or rec["user_id"] != user_id:
                continue
            ft = _tokens(rec["fact"].content)
            overlap = len(q & ft) / max(1, min(len(q), len(ft)))
            scored.append((1.0 - overlap, fid, rec["fact"]))
        scored.sort(key=lambda x: x[0])
        return [
            RetrievedMemory(
                id=fid, kind=f.kind, subject=f.subject, content=f.content,
                confidence=f.confidence, distance=dist, source="semantic",
            )
            for dist, fid, f in scored[:k]
        ]

    async def recent_facts(self, user_id, k) -> list[RetrievedMemory]:
        return await self.list_facts(user_id)

    async def touch_facts(self, ids) -> None:
        return None

    async def list_facts(self, user_id) -> list[RetrievedMemory]:
        return [
            RetrievedMemory(
                id=fid, kind=r["fact"].kind, subject=r["fact"].subject,
                content=r["fact"].content, confidence=r["fact"].confidence,
                distance=None, source="recent",
            )
            for fid, r in self.facts.items()
            if r["valid"] and r["user_id"] == user_id
        ]


class FakeLLM:
    """Returns canned JSON based on which system prompt is in play."""

    def __init__(self, extract_payload: dict, resolve_payload: dict) -> None:
        self.extract_payload = extract_payload
        self.resolve_payload = resolve_payload

    async def complete_json(self, system, user, temperature=0.0) -> dict:
        if "extract durable" in system:
            return self.extract_payload
        return self.resolve_payload


USER = str(uuid.uuid4())


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


async def test_consolidate_inserts_new_facts(store):
    extract = {
        "facts": [
            {"kind": "preference", "subject": "coffee",
             "content": "User prefers dark roast coffee", "confidence": 0.9},
            {"kind": "fact", "subject": "location",
             "content": "User lives in Mumbai", "confidence": 0.95},
        ]
    }
    llm = FakeLLM(extract, {"action": "insert"})
    graph = build_memory_graph(store, FactExtractor(llm), FactResolver(llm))

    out = await graph.ainvoke(
        {"mode": "consolidate", "user_id": USER,
         "messages": [{"role": "user", "content": "I like dark roast and live in Mumbai"}]}
    )

    assert len(out["written"]) == 2
    facts = await store.list_facts(USER)
    assert len(facts) == 2


async def test_consolidate_supersedes_changed_fact(store):
    # Seed an existing location fact.
    await store.add_fact(
        USER, ExtractedFact(kind=MemoryKind.FACT, subject="location",
                            content="User lives in Mumbai", confidence=0.95)
    )
    # New conversation says the location changed. The fake distance puts the old
    # fact in the "related but not identical" band, so the resolver consults the
    # LLM, which returns supersede on neighbor 0.
    extract = {"facts": [{"kind": "fact", "subject": "location",
                          "content": "User lives in Bangalore", "confidence": 0.95}]}
    resolve = {"action": "supersede", "target_index": 0, "reason": "moved"}
    llm = FakeLLM(extract, resolve)
    graph = build_memory_graph(store, FactExtractor(llm), FactResolver(llm))

    out = await graph.ainvoke(
        {"mode": "consolidate", "user_id": USER,
         "messages": [{"role": "user", "content": "Actually I moved to Bangalore"}]}
    )

    assert len(out["written"]) == 1
    current = {f.content for f in await store.list_facts(USER)}
    assert "User lives in Bangalore" in current
    assert "User lives in Mumbai" not in current  # superseded


async def test_consolidate_skips_duplicate(store):
    await store.add_fact(
        USER, ExtractedFact(kind=MemoryKind.PREFERENCE, subject="coffee",
                            content="User prefers dark roast coffee", confidence=0.9)
    )
    # Identical content -> token overlap 1.0 -> distance 0.0 -> skip, no LLM needed.
    extract = {"facts": [{"kind": "preference", "subject": "coffee",
                          "content": "User prefers dark roast coffee", "confidence": 0.9}]}
    llm = FakeLLM(extract, {"action": "skip"})
    graph = build_memory_graph(store, FactExtractor(llm), FactResolver(llm))

    out = await graph.ainvoke(
        {"mode": "consolidate", "user_id": USER,
         "messages": [{"role": "user", "content": "I really like dark roast coffee"}]}
    )

    assert out["written"] == []  # skipped
    assert len(await store.list_facts(USER)) == 1  # no duplicate added


async def test_retrieve_returns_memory_block(store):
    await store.add_fact(
        USER, ExtractedFact(kind=MemoryKind.FACT, subject="location",
                            content="User lives in Bangalore", confidence=0.95)
    )
    llm = FakeLLM({"facts": []}, {"action": "insert"})
    graph = build_memory_graph(store, FactExtractor(llm), FactResolver(llm))

    out = await graph.ainvoke(
        {"mode": "retrieve", "user_id": USER, "query": "where does the user live"}
    )

    assert "Bangalore" in out["memory_block"]
    assert len(out["retrieved"]) >= 1
