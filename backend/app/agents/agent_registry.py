"""Agent registry.

Maps a capability key to the specialist agent that handles it. Each agent
exposes `async arun(user_id, instruction, approved) -> {answer, calls}`. The
orchestrator delegates a plan step (or a single-route message) to the agent for
its capability; capabilities with no agent fall back to direct tool dispatch.
"""

from typing import Protocol


class SpecialistAgent(Protocol):
    async def arun(self, user_id: str, instruction: str,
                   approved: bool = False) -> dict: ...


class AgentRegistry:
    def __init__(self, agents: dict[str, SpecialistAgent]) -> None:
        self._agents = dict(agents)

    def get(self, capability: str) -> SpecialistAgent | None:
        return self._agents.get(capability)

    def has(self, capability: str) -> bool:
        return capability in self._agents

    def capabilities(self) -> list[str]:
        return sorted(self._agents)
