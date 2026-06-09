"""LangGraph state for the Planner Agent.

One TypedDict, two modes. `mode` selects whether we decompose a fresh goal or
revise an existing plan. Draft steps flow from the decompose/replan node into
the shared validate node. Fields stay serializable for checkpointing.
"""

from typing import Literal, TypedDict


class PlannerState(TypedDict, total=False):
    mode: Literal["plan", "replan"]
    goal: str
    context: str

    # --- replan inputs ---
    current_plan: dict   # serialized Plan
    feedback: str

    # --- intermediate ---
    draft_steps: list[dict]  # serialized PlanStep list, pre-validation

    # --- output ---
    plan: dict  # serialized, validated Plan (status ready|invalid, with order)
