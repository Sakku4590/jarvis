"""Memory store: the dual-store coordination layer.

Postgres holds the structured fact rows (kind, subject, confidence, validity
window, access stats). Chroma holds one vector per CURRENT fact, keyed by the
same id. The two are kept in sync here so nothing else has to think about it.

Why both: Postgres answers exact and recency questions and models supersession
(valid_from / valid_to); Chroma answers "what is semantically related". A fact
that gets superseded has its row closed (valid_to set) but kept for history,
and its vector deleted from Chroma so retrieval only ever surfaces current
facts.

Sync Chroma calls are pushed to a thread so they never block the event loop.
"""

import asyncio
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import MemoryFact
from app.db.session import SessionLocal
from app.memory.chroma_client import get_user_collection
from app.memory.embeddings import Embedder, get_embedder
from app.memory.schemas import ExtractedFact, MemoryKind, RetrievedMemory

log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BaseMemoryStore(ABC):
    """Storage interface the agent depends on. Lets tests swap in a fake."""

    @abstractmethod
    async def add_fact(
        self, user_id: str, fact: ExtractedFact, source_message_id: str | None = None
    ) -> str: ...

    @abstractmethod
    async def supersede_fact(
        self,
        user_id: str,
        old_id: str,
        new_fact: ExtractedFact,
        source_message_id: str | None = None,
    ) -> str: ...

    @abstractmethod
    async def semantic_search(
        self, user_id: str, query: str, k: int
    ) -> list[RetrievedMemory]: ...

    @abstractmethod
    async def recent_facts(self, user_id: str, k: int) -> list[RetrievedMemory]: ...

    @abstractmethod
    async def touch_facts(self, ids: list[str]) -> None: ...

    @abstractmethod
    async def list_facts(self, user_id: str) -> list[RetrievedMemory]: ...


class PgChromaMemoryStore(BaseMemoryStore):
    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or get_embedder()

    # --- writes -----------------------------------------------------------

    async def add_fact(
        self, user_id: str, fact: ExtractedFact, source_message_id: str | None = None
    ) -> str:
        fid = uuid.uuid4()
        vector = await self.embedder.embed_one(fact.content)

        async with SessionLocal() as session:
            row = MemoryFact(
                id=fid,
                user_id=uuid.UUID(user_id),
                kind=fact.kind.value,
                subject=fact.subject,
                content=fact.content,
                confidence=fact.confidence,
                source_message_id=(
                    uuid.UUID(source_message_id) if source_message_id else None
                ),
                chroma_id=str(fid),
                valid_from=_now(),
            )
            session.add(row)
            await session.commit()

        await self._chroma_add(user_id, str(fid), fact, vector)
        log.info("memory.add", user_id=user_id, fact_id=str(fid), kind=fact.kind.value)
        return str(fid)

    async def supersede_fact(
        self,
        user_id: str,
        old_id: str,
        new_fact: ExtractedFact,
        source_message_id: str | None = None,
    ) -> str:
        # Close the old row, drop its vector, then write the new fact.
        async with SessionLocal() as session:
            await session.execute(
                update(MemoryFact)
                .where(MemoryFact.id == uuid.UUID(old_id))
                .values(valid_to=_now())
            )
            await session.commit()

        await self._chroma_delete(user_id, [old_id])
        new_id = await self.add_fact(user_id, new_fact, source_message_id)
        log.info("memory.supersede", old=old_id, new=new_id)
        return new_id

    async def touch_facts(self, ids: list[str]) -> None:
        if not ids:
            return
        async with SessionLocal() as session:
            await session.execute(
                update(MemoryFact)
                .where(MemoryFact.id.in_([uuid.UUID(i) for i in ids]))
                .values(
                    last_accessed_at=_now(),
                    access_count=MemoryFact.access_count + 1,
                )
            )
            await session.commit()

    # --- reads ------------------------------------------------------------

    async def semantic_search(
        self, user_id: str, query: str, k: int
    ) -> list[RetrievedMemory]:
        vector = await self.embedder.embed_one(query)
        res = await asyncio.to_thread(self._chroma_query, user_id, vector, k)

        ids = (res.get("ids") or [[]])[0]
        distances = (res.get("distances") or [[]])[0]
        if not ids:
            return []

        by_id = {i: d for i, d in zip(ids, distances)}
        rows = await self._load_current(user_id, ids)
        out = [
            self._to_memory(row, distance=by_id.get(str(row.id)), source="semantic")
            for row in rows
        ]
        out.sort(key=lambda m: (m.distance if m.distance is not None else 1e9))
        return out

    async def recent_facts(self, user_id: str, k: int) -> list[RetrievedMemory]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(MemoryFact)
                .where(
                    MemoryFact.user_id == uuid.UUID(user_id),
                    MemoryFact.valid_to.is_(None),
                )
                .order_by(MemoryFact.created_at.desc())
                .limit(k)
            )
            rows = result.scalars().all()
        return [self._to_memory(r, distance=None, source="recent") for r in rows]

    async def list_facts(self, user_id: str) -> list[RetrievedMemory]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(MemoryFact)
                .where(
                    MemoryFact.user_id == uuid.UUID(user_id),
                    MemoryFact.valid_to.is_(None),
                )
                .order_by(MemoryFact.created_at.desc())
            )
            rows = result.scalars().all()
        return [self._to_memory(r, distance=None, source="recent") for r in rows]

    # --- helpers ----------------------------------------------------------

    async def _load_current(self, user_id: str, ids: list[str]) -> list[MemoryFact]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(MemoryFact).where(
                    MemoryFact.id.in_([uuid.UUID(i) for i in ids]),
                    MemoryFact.valid_to.is_(None),
                )
            )
            return list(result.scalars().all())

    @staticmethod
    def _to_memory(
        row: MemoryFact, distance: float | None, source: str
    ) -> RetrievedMemory:
        return RetrievedMemory(
            id=str(row.id),
            kind=MemoryKind(row.kind),
            subject=row.subject,
            content=row.content,
            confidence=row.confidence,
            distance=distance,
            source=source,
            created_at=row.created_at,
        )

    # Chroma calls are synchronous; the async methods above wrap them in a
    # thread where they sit on the hot path.
    async def _chroma_add(
        self, user_id: str, fact_id: str, fact: ExtractedFact, vector: list[float]
    ) -> None:
        def _do() -> None:
            get_user_collection(user_id).add(
                ids=[fact_id],
                embeddings=[vector],
                documents=[fact.content],
                metadatas=[
                    {
                        "kind": fact.kind.value,
                        "subject": fact.subject or "",
                        "confidence": fact.confidence,
                    }
                ],
            )

        await asyncio.to_thread(_do)

    async def _chroma_delete(self, user_id: str, ids: list[str]) -> None:
        await asyncio.to_thread(lambda: get_user_collection(user_id).delete(ids=ids))

    @staticmethod
    def _chroma_query(user_id: str, vector: list[float], k: int) -> dict:
        return get_user_collection(user_id).query(
            query_embeddings=[vector],
            n_results=k,
            include=["distances"],
        )


def get_memory_store() -> BaseMemoryStore:
    return PgChromaMemoryStore()
