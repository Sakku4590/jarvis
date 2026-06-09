"""Supervisor API.

A single entry point that runs a user message through the full orchestrator:
recall, route, execute, synthesize. The manual test surface for Phase 4.
"""

from functools import lru_cache

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.supervisor import SupervisorAgent, get_supervisor_agent

router = APIRouter(prefix="/supervisor", tags=["supervisor"])


@lru_cache
def _agent() -> SupervisorAgent:
    return get_supervisor_agent()


class RunRequest(BaseModel):
    user_id: str
    message: str
    thread_id: str | None = None
    approved: bool = False  # set true to clear the risk gate for a known action


@router.post("/run")
async def run(req: RunRequest) -> dict:
    out = await _agent().arun(req.user_id, req.message, req.thread_id, req.approved)
    return {
        "route": out.get("route"),
        "answer": out.get("answer"),
        "plan": out.get("plan"),
        "results": out.get("results", []),
    }
