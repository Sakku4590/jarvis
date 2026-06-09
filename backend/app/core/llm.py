"""LLM client.

A thin async wrapper that returns structured JSON, used by the memory
consolidation workflow for fact extraction and resolution. Supports OpenAI and
Ollama, selected by config. The provider client is created lazily so importing
this module never requires credentials (tests inject fakes instead).

This is intentionally minimal. The richer per-agent model router described in
the architecture spec arrives in a later phase.
"""

import json
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class LLMClient:
    """Provider-agnostic JSON completion client."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        settings = get_settings()
        self.provider = provider or settings.llm_provider
        self.model = model or settings.llm_model
        self._client: Any = None  # created lazily

    def _openai(self):
        if self._client is None:
            from openai import AsyncOpenAI

            settings = get_settings()
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

    async def complete_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
    ) -> dict:
        """Return a parsed JSON object from the model.

        The system prompt must instruct the model to reply with a single JSON
        object and nothing else.
        """
        if self.provider == "openai":
            return await self._openai_json(system, user, temperature)
        if self.provider == "ollama":
            return await self._ollama_json(system, user, temperature)
        raise ValueError(f"Unknown LLM provider: {self.provider}")

    async def complete_text(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
    ) -> str:
        """Return free-form text from the model (chat answers, synthesis)."""
        if self.provider == "openai":
            resp = await self._openai().chat.completions.create(
                model=self.model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.choices[0].message.content or ""
        if self.provider == "ollama":
            import httpx

            settings = get_settings()
            async with httpx.AsyncClient(timeout=settings.ollama_timeout) as http:
                resp = await http.post(
                    f"{settings.ollama_base_url}/api/chat",
                    json={
                        "model": self.model,
                        "stream": False,
                        "options": {"temperature": temperature},
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    },
                )
                resp.raise_for_status()
                return resp.json()["message"]["content"]
        raise ValueError(f"Unknown LLM provider: {self.provider}")

    async def _openai_json(self, system: str, user: str, temperature: float) -> dict:
        resp = await self._openai().chat.completions.create(
            model=self.model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return _safe_json(resp.choices[0].message.content or "{}")

    async def _ollama_json(self, system: str, user: str, temperature: float) -> dict:
        import httpx

        settings = get_settings()
        async with httpx.AsyncClient(timeout=settings.ollama_timeout) as http:
            resp = await http.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": self.model,
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": temperature},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            resp.raise_for_status()
            return _safe_json(resp.json()["message"]["content"])


def _safe_json(raw: str) -> dict:
    """Parse JSON, tolerating stray markdown fences."""
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("llm.json_parse_failed", raw=raw[:300])
        return {}
