"""Coding Agent API.

Delegate a coding task to the Coding Agent. Set approved=true to clear the risk
gate on code execution.
"""

from functools import lru_cache

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.coding_agent import CodingAgent, get_coding_agent

router = APIRouter(prefix="/code", tags=["code"])


@lru_cache
def _agent() -> CodingAgent:
    return get_coding_agent()


class CodeTaskRequest(BaseModel):
    user_id: str
    instruction: str
    approved: bool = False


@router.post("/task")
async def task(req: CodeTaskRequest) -> dict:
    return await _agent().arun(req.user_id, req.instruction, req.approved)
