"""Embeddings.

One pinned embedder per deployment. Changing the model means re-embedding
every stored fact, so the choice is config-driven and explicit.

Providers:
  - openai: text-embedding-3-small (default, 1536 dims)
  - ollama: e.g. nomic-embed-text, served locally
  - fake:   deterministic hash-based vectors. Dependency-free and offline, but
            NOT semantic. For tests and smoke runs only.
"""

import hashlib
from abc import ABC, abstractmethod

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class Embedder(ABC):
    dim: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into vectors."""

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]


class OpenAIEmbedder(Embedder):
    def __init__(self, model: str, dim: int) -> None:
        self.model = model
        self.dim = dim
        self._client = None

    def _c(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=get_settings().openai_api_key)
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self._c().embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]


class OllamaEmbedder(Embedder):
    def __init__(self, model: str, dim: int, base_url: str) -> None:
        self.model = model
        self.dim = dim
        self.base_url = base_url

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=60) as http:
            for text in texts:
                resp = await http.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                resp.raise_for_status()
                out.append(resp.json()["embedding"])
        return out


class FakeEmbedder(Embedder):
    """Deterministic, normalized vectors derived from a hash of the text.

    Same text always maps to the same vector, so duplicate detection works in
    tests. Different texts are near-orthogonal, so it does NOT model meaning.
    """

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def _vec(self, text: str) -> list[float]:
        # Expand a digest into `dim` bytes, center, then L2-normalize.
        raw = b""
        i = 0
        while len(raw) < self.dim:
            raw += hashlib.sha256(f"{text}:{i}".encode()).digest()
            i += 1
        vals = [(b - 127.5) / 127.5 for b in raw[: self.dim]]
        norm = sum(v * v for v in vals) ** 0.5 or 1.0
        return [v / norm for v in vals]


def get_embedder() -> Embedder:
    s = get_settings()
    if s.embedding_provider == "openai":
        return OpenAIEmbedder(s.embedding_model, s.embedding_dim)
    if s.embedding_provider == "ollama":
        return OllamaEmbedder(s.embedding_model, s.embedding_dim, s.ollama_base_url)
    log.info("embedder.using_fake")
    return FakeEmbedder()
