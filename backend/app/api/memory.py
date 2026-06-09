"""Memory API.

Endpoints to exercise the Memory Agent directly: push a conversation snippet
through consolidation, search what is remembered, and list current facts. These
are the manual test surface for Phase 2; the wider system will call the agent
in-process rather than over HTTP.
"""

from functools import lru_cache

from fastapi import APIRouter
from pydantic import BaseModel

from app.memory.agent import MemoryAgent, get_memory_agent
from app.memory.schemas import RetrievedMemory

router = APIRouter(prefix="/memory", tags=["memory"])


@lru_cache
def _agent() -> MemoryAgent:
    return get_memory_agent()


class TurnMessage(BaseModel):
    role: str = "user"
    content: str


class ConsolidateRequest(BaseModel):
    user_id: str
    messages: list[TurnMessage]
    source_message_id: str | None = None


@router.post("/consolidate")
async def consolidate(req: ConsolidateRequest) -> dict:
    result = await _agent().aconsolidate(
        req.user_id,
        [m.model_dump() for m in req.messages],
        req.source_message_id,
    )
    return {
        "extracted": result.get("extracted", []),
        "decisions": result.get("decisions", []),
        "written": result.get("written", []),
    }


@router.get("/search")
async def search(user_id: str, q: str) -> dict:
    result = await _agent().aretrieve(user_id, q)
    return {
        "memory_block": result.get("memory_block", ""),
        "memories": result.get("retrieved", []),
    }


@router.get("/facts")
async def facts(user_id: str) -> list[RetrievedMemory]:
    return await _agent().store.list_facts(user_id)
