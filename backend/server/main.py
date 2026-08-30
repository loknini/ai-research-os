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
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse, JSONResponse, Response

from . import config
from . import db
from .cron_scheduler import start_scheduler
from .development_runner import start_development_runner
from .errors import register_exception_handlers
from .llm import llm_client
from .routers import routers

FRONTEND_DIST = config.PROJECT_ROOT / "frontend" / "dist"


class SPAStaticFiles(StaticFiles):
    """Serve built assets and fall back to index.html for client-side routes."""

    async def get_response(self, path: str, scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.lstrip("/").startswith("api/"):
                return FileResponse(FRONTEND_DIST / "index.html")
            raise
        if response.status_code == 404 and not path.lstrip("/").startswith("api/"):
            return FileResponse(FRONTEND_DIST / "index.html")
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise the database schema once, idempotently, before serving.
    # `init_db` applies the aiosqlite WAL pragmas and the idempotent
    # `space_id` column migration for legacy/user tables.
    await db.init_db()
    # 启动 cron 调度器守护线程（多 Worker 各跑一个，靠 DB 原子领取防重）。
    start_scheduler()
    start_development_runner()
    yield


app = FastAPI(
    title="AI-Research-OS Backend",
    version="0.5.0",
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


@app.api_route(
    "/api/{unmatched_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
async def api_not_found(unmatched_path: str) -> JSONResponse:
    """Keep unknown API requests JSON-shaped instead of serving the SPA."""
    return JSONResponse(
        {"success": False, "error": "NOT_FOUND", "message": f"API route not found: /api/{unmatched_path}"},
        status_code=404,
    )

# Production SPA hosting -----------------------------------------------------
# Mounted last so that /api/* routes take precedence.  Only mounted when the
# frontend has been built (``npm run build`` -> frontend/dist).
if FRONTEND_DIST.exists():
    app.mount("/", SPAStaticFiles(directory=str(FRONTEND_DIST), html=True), name="spa")


@app.get("/")
async def root() -> dict:
    return {
        "success": True,
        "name": "AI-Research-OS Backend",
        "version": "0.5.0",
        "docs": "/docs",
        "health": "/api/healthz",
    }


__all__ = ["app"]
