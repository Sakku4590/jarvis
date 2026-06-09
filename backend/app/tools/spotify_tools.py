"""Spotify tools (capability "music").

Playback control and playlist creation are low-risk and reversible, so none are
approval-gated (music is the low-risk capability in the architecture). search is
READ; the rest are WRITE.
"""

from pydantic import BaseModel

from app.services.spotify_service import SpotifyService
from app.tools.schemas import RiskClass, ToolContext, ToolSpec


class SearchArgs(BaseModel):
    query: str
    type: str = "track"
    limit: int = 5
    action: str = "search"


class PlayArgs(BaseModel):
    query: str | None = None
    uris: list[str] | None = None
    context_uri: str | None = None
    action: str = "play"


class PauseArgs(BaseModel):
    action: str = "pause"


class SkipArgs(BaseModel):
    direction: str = "next"  # next | previous
    action: str = "skip"


class CreatePlaylistArgs(BaseModel):
    name: str
    public: bool = False
    track_uris: list[str] | None = None
    query: str | None = None
    action: str = "create_playlist"


def make_spotify_tools(service: SpotifyService) -> list[ToolSpec]:
    async def search(args: SearchArgs, ctx: ToolContext) -> dict:
        return await service.search(ctx.user_id, args.query, args.type, args.limit)

    async def play(args: PlayArgs, ctx: ToolContext) -> dict:
        return await service.play(ctx.user_id, args.query, args.uris, args.context_uri)

    async def pause(args: PauseArgs, ctx: ToolContext) -> dict:
        return await service.pause(ctx.user_id)

    async def skip(args: SkipArgs, ctx: ToolContext) -> dict:
        return await service.skip(ctx.user_id, args.direction)

    async def create_playlist(args: CreatePlaylistArgs, ctx: ToolContext) -> dict:
        return await service.create_playlist(
            ctx.user_id, args.name, args.public, args.track_uris, args.query)

    return [
        ToolSpec(name="music.search", capability="music",
                 description="Search Spotify for tracks/artists/playlists.",
                 args_schema=SearchArgs, handler=search,
                 risk_class=RiskClass.READ, requires_approval=False),
        ToolSpec(name="music.play", capability="music",
                 description="Play a track by query or URI on the active device.",
                 args_schema=PlayArgs, handler=play,
                 risk_class=RiskClass.WRITE, requires_approval=False),
        ToolSpec(name="music.pause", capability="music",
                 description="Pause playback.",
                 args_schema=PauseArgs, handler=pause,
                 risk_class=RiskClass.WRITE, requires_approval=False),
        ToolSpec(name="music.skip", capability="music",
                 description="Skip to the next or previous track.",
                 args_schema=SkipArgs, handler=skip,
                 risk_class=RiskClass.WRITE, requires_approval=False),
        ToolSpec(name="music.create_playlist", capability="music",
                 description="Create a playlist, optionally seeded by a search query.",
                 args_schema=CreatePlaylistArgs, handler=create_playlist,
                 risk_class=RiskClass.WRITE, requires_approval=False),
    ]
