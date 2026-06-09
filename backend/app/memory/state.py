"""LangGraph state for the Memory Agent.

A single TypedDict drives both flows. `mode` selects the entry branch. Fields
are kept serializable (plain dicts/strings) so the graph stays checkpointable
if a persistence layer is added later.
"""

from typing import Literal, TypedDict


class MemoryState(TypedDict, total=False):
    user_id: str
    mode: Literal["retrieve", "consolidate"]

    # --- retrieve flow ---
    query: str
    retrieved: list[dict]   # serialized RetrievedMemory objects
    memory_block: str

    # --- consolidate flow ---
    messages: list[dict]    # [{"role": ..., "content": ...}, ...]
    source_message_id: str | None
    extracted: list[dict]   # serialized ExtractedFact objects
    decisions: list[dict]   # serialized ResolutionDecision objects
    written: list[str]      # ids inserted or created via supersede
