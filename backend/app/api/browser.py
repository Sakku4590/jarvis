"""Browser Agent API.

Delegate a web task to the Browser Agent. Set approved=true to clear the risk
gate on a form submission.
"""

from functools import lru_cache

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.browser_agent import BrowserAgent, get_browser_agent

router = APIRouter(prefix="/browser", tags=["browser"])


@lru_cache
def _agent() -> BrowserAgent:
    return get_browser_agent()


class BrowserTaskRequest(BaseModel):
    user_id: str
    instruction: str
    approved: bool = False


@router.post("/task")
async def task(req: BrowserTaskRequest) -> dict:
    return await _agent().arun(req.user_id, req.instruction, req.approved)
