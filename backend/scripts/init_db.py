"""Dev helper: create all database tables directly from the SQLAlchemy models.

Use this to get unblocked locally when no Alembic migration exists yet:

    cd backend
    python scripts/init_db.py

It is idempotent (existing tables are left alone). For production, generate and
apply real migrations instead, so schema changes are versioned:

    alembic revision --autogenerate -m "initial schema"
    alembic upgrade head
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import asyncio

import app.db.models  # noqa: F401  -- registers every table on Base.metadata
from app.db.base import Base
from app.db.session import engine


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Tables present:", ", ".join(sorted(Base.metadata.tables)))


if __name__ == "__main__":
    asyncio.run(main())
