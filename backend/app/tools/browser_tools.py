"""Browser tools.

Four tools under the "browser" capability:
  - browser.open / browser.search / browser.extract: navigation and reading,
    classified READ.
  - browser.fill: fills (and optionally submits) a form. Submitting a form is a
    real action (login, purchase, post), so this is WRITE and approval-gated.

Extracted text is returned verbatim as data; the agent is responsible for
treating it as untrusted, never as instructions.
"""

from pydantic import BaseModel

from app.services.browser_service import BrowserService
from app.tools.schemas import RiskClass, ToolContext, ToolSpec


class OpenArgs(BaseModel):
    url: str
    action: str = "open"


class SearchArgs(BaseModel):
    query: str
    max_results: int = 5
    action: str = "search"


class ExtractArgs(BaseModel):
    url: str
    selector: str | None = None
    max_chars: int | None = None
    action: str = "extract"


class FillArgs(BaseModel):
    url: str
    fields: dict[str, str]
    submit: bool = False
    submit_selector: str | None = None
    action: str = "fill"


def make_browser_tools(service: BrowserService) -> list[ToolSpec]:
    async def open_(args: OpenArgs, ctx: ToolContext) -> dict:
        return (await service.open(args.url)).model_dump()

    async def search(args: SearchArgs, ctx: ToolContext) -> dict:
        return (await service.search(args.query, args.max_results)).model_dump()

    async def extract(args: ExtractArgs, ctx: ToolContext) -> dict:
        return (await service.extract(args.url, args.selector, args.max_chars)).model_dump()

    async def fill(args: FillArgs, ctx: ToolContext) -> dict:
        return (await service.fill(
            args.url, args.fields, args.submit, args.submit_selector)).model_dump()

    return [
        ToolSpec(name="browser.open", capability="browser",
                 description="Open a URL and return its title and status.",
                 args_schema=OpenArgs, handler=open_,
                 risk_class=RiskClass.READ, requires_approval=False),
        ToolSpec(name="browser.search", capability="browser",
                 description="Search the web and return result titles and URLs.",
                 args_schema=SearchArgs, handler=search,
                 risk_class=RiskClass.READ, requires_approval=False),
        ToolSpec(name="browser.extract", capability="browser",
                 description="Open a URL and extract page text (optionally by CSS selector).",
                 args_schema=ExtractArgs, handler=extract,
                 risk_class=RiskClass.READ, requires_approval=False),
        ToolSpec(name="browser.fill", capability="browser",
                 description="Fill form fields by selector and optionally submit. Submitting acts on the site.",
                 args_schema=FillArgs, handler=fill,
                 risk_class=RiskClass.WRITE, requires_approval=True),
    ]
