"""File Agent API.

Delegate a natural-language file task to the File Agent. Set approved=true to
clear the risk gate on a delete.
"""

from functools import lru_cache

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.file_agent import FileAgent, get_file_agent

router = APIRouter(prefix="/files", tags=["files"])


@lru_cache
def _agent() -> FileAgent:
    return get_file_agent()


class FileTaskRequest(BaseModel):
    user_id: str
    instruction: str
    approved: bool = False


@router.post("/task")
async def task(req: FileTaskRequest) -> dict:
    return await _agent().arun(req.user_id, req.instruction, req.approved)
