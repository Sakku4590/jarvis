"""Tool layer schemas.

The common contract every tool is registered with, plus the standard result
envelope every tool execution returns. Agents never see a raw integration
response; they see a ToolResult. This uniformity is what keeps the executor and
the agent prompts simple.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, Field


class RiskClass(str, Enum):
    READ = "read"              # no side effects
    WRITE = "write"            # creates or modifies state
    DESTRUCTIVE = "destructive"  # irreversible or externally visible (send, delete)


class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    INVALID_ARGS = "invalid_args"
    NOT_PERMITTED = "not_permitted"
    PENDING_APPROVAL = "pending_approval"


@dataclass
class ToolContext:
    """Per-invocation context threaded through the pipeline to the handler."""

    user_id: str
    thread_id: str | None = None
    approved: bool = False           # set true once a human approved the action
    deps: dict = field(default_factory=dict)  # injected handles (e.g. memory agent)


# A handler takes validated args (a pydantic model) plus context and returns a
# plain dict that becomes ToolResult.data.
ToolHandler = Callable[[BaseModel, ToolContext], Awaitable[dict]]


@dataclass
class ToolSpec:
    name: str                 # globally unique, convention "<capability>.<action>"
    capability: str           # the capability this tool belongs to
    description: str          # read by the selector/LLM
    args_schema: type[BaseModel]
    handler: ToolHandler
    risk_class: RiskClass = RiskClass.READ
    requires_approval: bool = False


class ToolError(BaseModel):
    code: str
    message: str


class ToolResult(BaseModel):
    ok: bool
    status: ToolStatus
    data: dict | None = None
    error: ToolError | None = None
    meta: dict = Field(default_factory=dict)  # tool, duration_ms, attempts

    @classmethod
    def success(cls, data: dict, meta: dict) -> "ToolResult":
        return cls(ok=True, status=ToolStatus.SUCCESS, data=data, meta=meta)

    @classmethod
    def failure(cls, status: ToolStatus, code: str, message: str, meta: dict) -> "ToolResult":
        return cls(
            ok=False, status=status, error=ToolError(code=code, message=message), meta=meta
        )
