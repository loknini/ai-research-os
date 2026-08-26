"""FastAPI application entrypoint for the AI-Research-OS backend.

Run with::
    uvicorn backend.server.main:app --port 8000

Responsibilities:
  * CORS (``*`` in dev, configurable via ``CORS_ORIGINS``)
  * Mount all routers under ``/api``
  * Initialise the SQLite schema on startup
  * In production, serve the built ``frontend/dist`` SPA (if present)
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from . import db
from .cron_scheduler import start_scheduler
from .errors import register_exception_handlers
from .llm import llm_client
from .routers import routers

FRONTEND_DIST = config.PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise the database schema once, idempotently, before serving.
    # `init_db` applies the aiosqlite WAL pragmas and the idempotent
    # `space_id` column migration for legacy/user tables.
    await db.init_db()
    # 启动 cron 调度器守护线程（多 Worker 各跑一个，靠 DB 原子领取防重）。
    start_scheduler()
    yield


app = FastAPI(
    title="AI-Research-OS Backend",
    version="0.3.0",
    lifespan=lifespan,
)

# CORS ----------------------------------------------------------------------
origins = config.get_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Unified error handling ----------------------------------------------------
register_exception_handlers(app)

# Routers -------------------------------------------------------------------
for _router in routers:
    app.include_router(_router)

# Production SPA hosting -----------------------------------------------------
# Mounted last so that /api/* routes take precedence.  Only mounted when the
# frontend has been built (``npm run build`` -> frontend/dist).
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="spa")


@app.get("/")
async def root() -> dict:
    return {
        "success": True,
        "name": "AI-Research-OS Backend",
        "version": "0.3.0",
        "docs": "/docs",
        "health": "/api/healthz",
    }


__all__ = ["app"]
