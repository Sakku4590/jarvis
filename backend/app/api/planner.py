"""Planner API.

Endpoints to exercise the Planner Agent: decompose a goal into a validated plan,
and revise a plan given feedback. This is the manual test surface for Phase 3.
"""

from functools import lru_cache

from fastapi import APIRouter
from pydantic import BaseModel

from app.planner.agent import PlannerAgent, get_planner_agent
from app.planner.capabilities import default_registry
from app.planner.schemas import Plan

router = APIRouter(prefix="/planner", tags=["planner"])


@lru_cache
def _agent() -> PlannerAgent:
    return get_planner_agent()


class PlanRequest(BaseModel):
    goal: str
    context: str | None = None


class ReplanRequest(BaseModel):
    goal: str
    current_plan: Plan
    feedback: str
    context: str | None = None


@router.get("/capabilities")
async def capabilities() -> dict:
    return {"capabilities": default_registry().keys()}


@router.post("/plan")
async def plan(req: PlanRequest) -> Plan:
    return await _agent().aplan(req.goal, req.context)


@router.post("/replan")
async def replan(req: ReplanRequest) -> Plan:
    return await _agent().areplan(req.goal, req.current_plan, req.feedback, req.context)
