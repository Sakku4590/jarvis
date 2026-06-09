"""FastAPI application entrypoint.

Wires together configuration, logging, CORS, and routers. The lifespan handler
runs startup/shutdown logic: here it configures logging and disposes the DB
engine cleanly on exit. Agents, tools, and the chat endpoint are added in later
phases; Phase 1 ships a healthy, observable skeleton.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    browser,
    code,
    dashboard,
    files,
    gmail,
    health,
    jarvis,
    memory,
    planner,
    spotify,
    supervisor,
    whatsapp,
)
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log = get_logger("app.startup")
    settings = get_settings()
    log.info("app.start", app_name=settings.app_name, env=settings.app_env)
    yield
    # Clean shutdown: release the connection pool.
    await engine.dispose()
    log.info("app.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(memory.router)
    app.include_router(planner.router)
    app.include_router(supervisor.router)
    app.include_router(files.router)
    app.include_router(code.router)
    app.include_router(browser.router)
    app.include_router(gmail.router)
    app.include_router(spotify.router)
    app.include_router(whatsapp.router)
    app.include_router(jarvis.router)
    app.include_router(dashboard.router)

    @app.get("/")
    async def root() -> dict:
        return {"service": settings.app_name, "docs": "/docs"}

    return app


app = create_app()
