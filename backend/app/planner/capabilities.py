"""Capability registry.

A planner has to plan against something. This is a declarative catalog of the
capabilities the wider system intends to offer: keys, human descriptions, and
example inputs the LLM can pattern off. These are descriptions ONLY. No agent
or executor is implemented here; the specialist agents that fulfil these
capabilities arrive in later phases. The registry exists so the planner can
(a) tell the LLM what is available and (b) validate that every step targets a
real capability.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Capability:
    key: str
    description: str
    example_inputs: dict = field(default_factory=dict)


# The intended capability surface of the assistant. Edit freely; the planner
# adapts to whatever is registered.
DEFAULT_CAPABILITIES: list[Capability] = [
    Capability("file", "Read, search, write, move, or summarize local and cloud files.",
               {"action": "search", "query": "contract pdf"}),
    Capability("email", "Search, read, draft, send, label, or archive email.",
               {"action": "draft", "to": "john@example.com", "subject": "..."}),
    Capability("calendar", "List, create, update, delete events; find free slots.",
               {"action": "create", "title": "...", "start": "2026-01-01T09:00"}),
    Capability("browser", "Navigate, click, extract content, or fill forms on the web.",
               {"action": "extract", "url": "https://..."}),
    Capability("code", "Read a repo, edit files, run code or tests in a sandbox.",
               {"action": "run", "language": "python", "entry": "main.py"}),
    Capability("music", "Control Spotify: play, pause, queue, search, manage playlists.",
               {"action": "play", "query": "lo-fi beats"}),
    Capability("messaging", "Read, search, or send WhatsApp messages.",
               {"action": "send", "to": "+10000000000", "text": "..."}),
    Capability("memory", "Retrieve facts about the user or store new ones.",
               {"action": "retrieve", "query": "user's travel preferences"}),
]


class CapabilityRegistry:
    def __init__(self, capabilities: list[Capability] | None = None) -> None:
        caps = capabilities if capabilities is not None else DEFAULT_CAPABILITIES
        self._by_key: dict[str, Capability] = {c.key: c for c in caps}

    def has(self, key: str) -> bool:
        return key in self._by_key

    def keys(self) -> list[str]:
        return list(self._by_key)

    def catalog_text(self) -> str:
        """Render the catalog for the planner prompt."""
        lines = []
        for c in self._by_key.values():
            example = f" example inputs: {c.example_inputs}" if c.example_inputs else ""
            lines.append(f"- {c.key}: {c.description}{example}")
        return "\n".join(lines)


def default_registry() -> CapabilityRegistry:
    return CapabilityRegistry()
