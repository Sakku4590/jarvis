"""Code tools.

Four tools under the "code" capability:
  - code.generate / code.review / code.debug: pure LLM operations, no side
    effects, classified READ.
  - code.execute: runs Python in the sandbox. DESTRUCTIVE and approval-gated,
    so the pipeline holds it unless the request is approved.

The generate/review/debug handlers use the text LLM; execute uses the sandbox.
Both are injected so the tools are testable with fakes.
"""

from pydantic import BaseModel

from app.core.llm import LLMClient
from app.services.code_sandbox import CodeSandbox
from app.tools.schemas import RiskClass, ToolContext, ToolSpec

_GENERATE_SYSTEM = (
    "You are an expert programmer. Write clean, correct, self-contained {lang} "
    "code for the task. Output ONLY the code: no prose, no markdown fences."
)
_REVIEW_SYSTEM = (
    "You are a senior code reviewer. Review the {lang} code for bugs, security "
    "issues, and clarity. Be specific and concise; reference lines or symbols."
)
_DEBUG_SYSTEM = (
    "You are debugging {lang} code. Given the code and an error or traceback, "
    "explain the most likely cause and the concrete fix. Be concise."
)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: t.rfind("```")]
    return t.strip()


class GenerateArgs(BaseModel):
    task: str
    language: str = "python"
    context: str = ""
    action: str = "generate"


class ReviewArgs(BaseModel):
    code: str
    language: str = "python"
    action: str = "review"


class DebugArgs(BaseModel):
    code: str
    error: str = ""
    language: str = "python"
    action: str = "debug"


class ExecuteArgs(BaseModel):
    code: str
    timeout: float | None = None
    action: str = "execute"


def make_code_tools(sandbox: CodeSandbox, llm: LLMClient) -> list[ToolSpec]:
    async def generate(args: GenerateArgs, ctx: ToolContext) -> dict:
        system = _GENERATE_SYSTEM.format(lang=args.language)
        user = args.task if not args.context else f"{args.context}\n\nTask: {args.task}"
        text = await llm.complete_text(system, user)
        return {"language": args.language, "code": _strip_fences(text)}

    async def review(args: ReviewArgs, ctx: ToolContext) -> dict:
        system = _REVIEW_SYSTEM.format(lang=args.language)
        text = await llm.complete_text(system, args.code)
        return {"review": text}

    async def debug(args: DebugArgs, ctx: ToolContext) -> dict:
        system = _DEBUG_SYSTEM.format(lang=args.language)
        user = f"Code:\n{args.code}\n\nError:\n{args.error}"
        text = await llm.complete_text(system, user)
        return {"analysis": text}

    async def execute(args: ExecuteArgs, ctx: ToolContext) -> dict:
        result = await sandbox.run(args.code, timeout=args.timeout)
        return result.model_dump()

    return [
        ToolSpec(name="code.generate", capability="code",
                 description="Generate code for a task. Returns the code.",
                 args_schema=GenerateArgs, handler=generate,
                 risk_class=RiskClass.READ, requires_approval=False),
        ToolSpec(name="code.review", capability="code",
                 description="Review code for bugs, security issues, and clarity.",
                 args_schema=ReviewArgs, handler=review,
                 risk_class=RiskClass.READ, requires_approval=False),
        ToolSpec(name="code.debug", capability="code",
                 description="Diagnose an error in code and propose a fix.",
                 args_schema=DebugArgs, handler=debug,
                 risk_class=RiskClass.READ, requires_approval=False),
        ToolSpec(name="code.execute", capability="code",
                 description="Execute Python in a sandbox. Returns stdout, stderr, exit code.",
                 args_schema=ExecuteArgs, handler=execute,
                 risk_class=RiskClass.DESTRUCTIVE, requires_approval=True),
    ]
