"""File tools.

Wraps the FileService in the standard ToolSpec contract so the tools plug into
the registry, selector, pipeline, and the File Agent. Risk classes are set with
intent: read and search are READ, create and rename are WRITE, and delete is
DESTRUCTIVE and approval-gated, so a delete is held by the pipeline's risk gate
unless the request is approved.

Service calls are synchronous, so handlers push them to a thread to keep the
event loop free.
"""

import asyncio

from pydantic import BaseModel

from app.services.file_service import FileService
from app.tools.schemas import RiskClass, ToolContext, ToolSpec


class CreateArgs(BaseModel):
    path: str
    content: str = ""
    overwrite: bool = False
    action: str = "create"


class ReadArgs(BaseModel):
    path: str
    action: str = "read"


class DeleteArgs(BaseModel):
    path: str
    action: str = "delete"


class RenameArgs(BaseModel):
    src: str
    dst: str
    overwrite: bool = False
    action: str = "rename"


class SearchArgs(BaseModel):
    query: str = ""
    glob: str = "*"
    search_content: bool = False
    path: str = "."
    action: str = "search"


def make_file_tools(service: FileService) -> list[ToolSpec]:
    async def create(args: CreateArgs, ctx: ToolContext) -> dict:
        return await asyncio.to_thread(
            service.create, args.path, args.content, args.overwrite)

    async def read(args: ReadArgs, ctx: ToolContext) -> dict:
        return await asyncio.to_thread(service.read, args.path)

    async def delete(args: DeleteArgs, ctx: ToolContext) -> dict:
        return await asyncio.to_thread(service.delete, args.path)

    async def rename(args: RenameArgs, ctx: ToolContext) -> dict:
        return await asyncio.to_thread(
            service.rename, args.src, args.dst, args.overwrite)

    async def search(args: SearchArgs, ctx: ToolContext) -> dict:
        return await asyncio.to_thread(
            service.search, args.query, args.glob, args.search_content, args.path)

    return [
        ToolSpec(name="file.create", capability="file",
                 description="Create a file with optional content. Set overwrite to replace.",
                 args_schema=CreateArgs, handler=create,
                 risk_class=RiskClass.WRITE, requires_approval=False),
        ToolSpec(name="file.read", capability="file",
                 description="Read a text file's contents.",
                 args_schema=ReadArgs, handler=read,
                 risk_class=RiskClass.READ, requires_approval=False),
        ToolSpec(name="file.delete", capability="file",
                 description="Delete a file. Irreversible.",
                 args_schema=DeleteArgs, handler=delete,
                 risk_class=RiskClass.DESTRUCTIVE, requires_approval=True),
        ToolSpec(name="file.rename", capability="file",
                 description="Rename or move a file within the workspace.",
                 args_schema=RenameArgs, handler=rename,
                 risk_class=RiskClass.WRITE, requires_approval=False),
        ToolSpec(name="file.search", capability="file",
                 description="Search files by name (and optionally content) under a path.",
                 args_schema=SearchArgs, handler=search,
                 risk_class=RiskClass.READ, requires_approval=False),
    ]
