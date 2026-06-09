"""Orchestrator API: the single Jarvis entrypoint.

POST /jarvis/run sends a message through the unified workflow: recall, classify,
and route into chat, a single specialist, or a planned multi-agent run.
"""

from functools import lru_cache

import time

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.orchestrator import Orchestrator, get_orchestrator
from app.observability.activity import get_activity_store

router = APIRouter(prefix="/jarvis", tags=["jarvis"])


@lru_cache
def _orchestrator() -> Orchestrator:
    return get_orchestrator()


class RunRequest(BaseModel):
    user_id: str
    message: str
    approved: bool = False


@router.post("/run")
async def run(req: RunRequest) -> dict:
    out = await _orchestrator().arun(req.user_id, req.message, req.approved)
    get_activity_store().record_task({
        "time": time.time(),
        "user_id": req.user_id,
        "message": req.message,
        "route": out.get("route"),
        "answer": out.get("answer"),
        "steps": [{"step_id": r.get("step_id"), "capability": r.get("capability"),
                   "status": r.get("status")} for r in out.get("results", [])],
    })
    return out
