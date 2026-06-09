"""Phase 9 tests: Spotify OAuth URL builder and the agent loop with a fake service."""

from urllib.parse import parse_qs, urlparse

import pytest

from app.agents.spotify_agent import SpotifyAgent, spotify_registry
from app.integrations.spotify_oauth import build_authorize_url
from app.services.spotify_service import NotConnected, SpotifyService


# --- pure OAuth URL builder ----------------------------------------------

def test_build_authorize_url():
    url = build_authorize_url(
        "client123", "http://localhost/cb",
        ["user-modify-playback-state", "playlist-modify-private"], "state-xyz")
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.spotify.com"
    assert q["client_id"] == ["client123"]
    assert q["response_type"] == ["code"]
    assert q["state"] == ["state-xyz"]
    assert "user-modify-playback-state" in q["scope"][0]


# --- fake service + agent -------------------------------------------------

class FakeSpotify(SpotifyService):
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected
        self.calls: list[str] = []

    def _check(self):
        if not self.connected:
            raise NotConnected()

    async def search(self, user_id, query, type_="track", limit=5):
        self._check(); self.calls.append("search")
        return {"query": query, "results": [{"name": "Song", "uri": "spotify:track:1"}]}

    async def play(self, user_id, query=None, uris=None, context_uri=None):
        self._check(); self.calls.append("play")
        return {"playing": True, "query": query, "uris": uris}

    async def pause(self, user_id):
        self._check(); self.calls.append("pause")
        return {"paused": True}

    async def skip(self, user_id, direction="next"):
        self._check(); self.calls.append("skip")
        return {"skipped": direction}

    async def create_playlist(self, user_id, name, public=False, track_uris=None, query=None):
        self._check(); self.calls.append("create_playlist")
        return {"playlist_id": "pl1", "name": name, "tracks_added": len(track_uris or [])}


def _agent(decisions, service=None) -> tuple[SpotifyAgent, FakeSpotify]:
    svc = service or FakeSpotify()

    class ScriptedLLM:
        def __init__(self, d): self._d = list(d)
        async def complete_json(self, system, user, temperature=0.0):
            return self._d.pop(0) if self._d else {"action": "finish", "answer": "done"}
        async def complete_text(self, system, user, temperature=0.3):
            return ""

    return SpotifyAgent(registry=spotify_registry(svc), llm=ScriptedLLM(decisions)), svc


async def test_play_by_query():
    agent, svc = _agent([
        {"action": "call", "tool": "music.play", "args": {"query": "lo-fi beats"}},
        {"action": "finish", "answer": "Playing lo-fi beats."},
    ])
    out = await agent.arun("u1", "play some lo-fi")
    assert svc.calls == ["play"]
    assert out["calls"][0]["data"]["playing"] is True
    assert out["answer"] == "Playing lo-fi beats."


async def test_pause_and_skip():
    agent, svc = _agent([
        {"action": "call", "tool": "music.pause", "args": {}},
        {"action": "call", "tool": "music.skip", "args": {"direction": "next"}},
        {"action": "finish", "answer": "Paused then skipped."},
    ])
    out = await agent.arun("u1", "pause then skip")
    assert svc.calls == ["pause", "skip"]
    assert out["calls"][0]["data"]["paused"] is True
    assert out["calls"][1]["data"]["skipped"] == "next"


async def test_create_playlist():
    agent, svc = _agent([
        {"action": "call", "tool": "music.create_playlist",
         "args": {"name": "Focus", "query": "deep focus", "track_uris": ["a", "b"]}},
        {"action": "finish", "answer": "Created Focus."},
    ])
    out = await agent.arun("u1", "make me a focus playlist")
    assert svc.calls == ["create_playlist"]
    assert out["calls"][0]["data"]["name"] == "Focus"
    assert out["calls"][0]["data"]["tracks_added"] == 2


async def test_not_connected():
    agent, _ = _agent([
        {"action": "call", "tool": "music.play", "args": {"query": "x"}},
        {"action": "finish", "answer": "Not connected."},
    ], service=FakeSpotify(connected=False))
    out = await agent.arun("u1", "play music")
    assert out["calls"][0]["status"] == "error"
    assert "not_connected" in out["calls"][0]["error"]["message"]
