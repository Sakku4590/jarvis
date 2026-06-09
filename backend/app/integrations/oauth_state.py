"""Shared OAuth state store.

The OAuth `state` value issued at authorize time must be readable at callback
time, even though those two requests may land on different worker processes
(the server runs several). A per-process dict cannot do that, which caused
"invalid or expired OAuth state". This stores state in Redis, shared by all
workers, with a short TTL. If Redis is unavailable (e.g. tests), it falls back
to an in-process dict.

A state maps to "<provider>:<user_id>" so the callback knows whose tokens to
store.
"""

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_PREFIX = "oauth:state:"
_TTL_SECONDS = 600  # a login must complete within 10 minutes
_memory_fallback: dict[str, str] = {}


def _redis():
    try:
        import redis  # lazy; redis==5.2.1 is in requirements

        return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("oauth_state.redis_unavailable", error=str(exc))
        return None


def put_state(state: str, provider: str, user_id: str) -> None:
    value = f"{provider}:{user_id}"
    client = _redis()
    if client is None:
        _memory_fallback[state] = value
        return
    try:
        client.setex(_PREFIX + state, _TTL_SECONDS, value)
    except Exception as exc:  # noqa: BLE001
        log.warning("oauth_state.put_failed", error=str(exc))
        _memory_fallback[state] = value


def take_state(state: str, provider: str) -> str | None:
    """Return user_id for this state+provider and delete it, or None if absent."""
    client = _redis()
    raw = None
    if client is not None:
        try:
            key = _PREFIX + state
            raw = client.get(key)
            if raw is not None:
                client.delete(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("oauth_state.take_failed", error=str(exc))
    if raw is None:
        raw = _memory_fallback.pop(state, None)
    if raw is None:
        return None
    stored_provider, _, user_id = raw.partition(":")
    if stored_provider != provider:
        return None
    return user_id
