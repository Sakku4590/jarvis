"""ChromaDB client wrapper.

Owns the vector-store client lifecycle, a per-user collection helper, and a
heartbeat for the health endpoint. The chromadb package is imported lazily
inside the functions so importing this module (and anything that depends on it)
does not pull in the heavy client at startup or in tests that never touch the
vector store.

We use Chroma's HttpClient to talk to the standalone chroma container rather
than embedding a local instance, so the vector store is a real service we can
scale and back up independently.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


@lru_cache
def get_chroma_client():
    """Return a cached Chroma HTTP client."""
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    settings = get_settings()
    log.info(
        "chroma.connect",
        host=settings.chroma_host,
        port=settings.chroma_effective_port,
    )
    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_effective_port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_user_collection(user_id: str):
    """Get or create the memory collection for a given user.

    One collection per user keeps namespaces clean and makes per-user deletion
    trivial. Distance is cosine, which pairs well with normalized text
    embeddings.
    """
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=f"memory_{user_id}",
        metadata={"hnsw:space": "cosine"},
    )


def chroma_healthy() -> bool:
    """Lightweight heartbeat used by the health endpoint."""
    try:
        get_chroma_client().heartbeat()
        return True
    except Exception as exc:  # noqa: BLE001 - health check reports, never raises
        log.warning("chroma.health_failed", error=str(exc))
        return False
