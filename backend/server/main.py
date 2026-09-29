"""AI-Research-OS 后端入口：创建 FastAPI 应用并装配中间件、路由和静态站点。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse, JSONResponse, Response

from .core import config
from .core.errors import register_exception_handlers
from .core.lifecycle import lifespan
from .core.logging import RequestIdMiddleware, configure_logging
from .routers import routers

FRONTEND_DIST = config.PROJECT_ROOT / "frontend" / "dist"
configure_logging()


class SPAStaticFiles(StaticFiles):
    """提供构建产物；非 API 路径不存在时回退到 SPA 的 ``index.html``。"""

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

app = FastAPI(
    title="AI-Research-OS Backend",
    version="0.5.0",
    lifespan=lifespan,
)
app.add_middleware(RequestIdMiddleware)

# 跨域配置 ------------------------------------------------------------------
origins = config.get_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 统一异常处理 ---------------------------------------------------------------
register_exception_handlers(app)

# 路由装配 ------------------------------------------------------------------
for _router in routers:
    app.include_router(_router)


@app.api_route(
    "/api/{unmatched_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
async def api_not_found(unmatched_path: str) -> JSONResponse:
    """未知 API 始终返回 JSON，不能被 SPA 回退页面吞掉。"""
    return JSONResponse(
        {"success": False, "error": "NOT_FOUND", "message": f"API route not found: /api/{unmatched_path}"},
        status_code=404,
    )

# 生产 SPA 托管 --------------------------------------------------------------
# 最后挂载以保证 /api/* 优先；仅在前端已经构建时启用。
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
