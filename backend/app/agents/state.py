"""LangGraph state for the Supervisor Agent.

Carries a request from arrival to answer: the message, recalled memory, the
routing decision, an optional plan, per-step execution results, and the final
synthesized answer. Serializable for checkpointing.
"""

from typing import TypedDict


class SupervisorState(TypedDict, total=False):
    user_id: str
    thread_id: str | None
    message: str
    approved: bool

    # cross-cutting
    memory_block: str

    # routing
    route: str            # chat | single | plan
    capability: str | None

    # plan path
    plan: dict            # serialized Plan

    # execution
    results: list[dict]   # serialized StepResult list

    # output
    answer: str
