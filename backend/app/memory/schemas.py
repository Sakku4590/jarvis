"""Memory schemas.

The data shapes that flow through the memory subsystem. Kept separate from the
SQLAlchemy models (which are the storage shape) so the agent, retrieval, and
consolidation code passes around validated, serializable objects.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MemoryKind(str, Enum):
    PREFERENCE = "preference"
    PERSON = "person"
    PROJECT = "project"
    FACT = "fact"
    PROCEDURE = "procedure"


class ExtractedFact(BaseModel):
    """A candidate fact pulled from conversation, before resolution."""

    kind: MemoryKind
    subject: str | None = None
    content: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class RetrievedMemory(BaseModel):
    """A stored fact returned from retrieval, with its match score."""

    id: str
    kind: MemoryKind
    subject: str | None
    content: str
    confidence: float
    # Cosine distance from the query (lower is closer). None for structured
    # (recency-based) hits that were not scored by similarity.
    distance: float | None = None
    source: str = "semantic"  # semantic | recent
    created_at: datetime | None = None


class ResolutionDecision(BaseModel):
    """What to do with one extracted fact after comparing against memory."""

    fact: ExtractedFact
    action: str  # insert | skip | supersede
    target_id: str | None = None  # the fact being superseded or touched
    reason: str | None = None


class RetrievedContext(BaseModel):
    """The final retrieval payload handed to the caller."""

    memories: list[RetrievedMemory] = Field(default_factory=list)
    memory_block: str = ""  # formatted, budget-capped text for prompt injection
