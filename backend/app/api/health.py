"""Health and readiness endpoints.

`/health` is a cheap liveness probe (the process is up).
`/health/ready` actually pings Postgres, Redis, and Chroma, so you can tell at
a glance whether the whole stack wired up correctly.
"""

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_db
from app.memory.chroma_client import chroma_healthy

router = APIRouter(tags=["health"])
log = get_logger(__name__)


@router.get("/health")
async def health() -> dict:
    """Liveness: is the API process responding at all."""
    return {"status": "ok", "service": get_settings().app_name}


@router.get("/health/ready")
async def readiness(db: AsyncSession = Depends(get_db)) -> dict:
    """Readiness: can we actually reach every backing service."""
    settings = get_settings()
    checks: dict[str, bool] = {}

    # Postgres
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = True
    except Exception as exc:  # noqa: BLE001
        log.warning("health.postgres_failed", error=str(exc))
        checks["postgres"] = False

    # Redis
    try:
        client = aioredis.from_url(settings.redis_url)
        checks["redis"] = bool(await client.ping())
        await client.aclose()
    except Exception as exc:  # noqa: BLE001
        log.warning("health.redis_failed", error=str(exc))
        checks["redis"] = False

    # Chroma
    checks["chroma"] = chroma_healthy()

    all_ok = all(checks.values())
    return {"status": "ready" if all_ok else "degraded", "checks": checks}
