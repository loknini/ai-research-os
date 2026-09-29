"""共享的错误处理与 SSE 辅助函数。

所有 REST 错误统一返回 ``{success: false, error, message}`` JSON，以维持前端依赖的
响应结构。SSE 流式端点使用 ``SSE_DONE`` 结束标记，以及 ``sse_event``、
``sse_error`` 辅助函数。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SSE 常量
# ---------------------------------------------------------------------------
SSE_DONE = "[DONE]"
SSE_EVENT_TYPES = {"phase_start", "start", "progress", "complete", "error"}


class APIError(Exception):
    """可映射为 JSON 错误响应体的应用级异常。"""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR", status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


# ---------------------------------------------------------------------------
# 响应体辅助函数
# ---------------------------------------------------------------------------
def error_body(code: str, message: str, **extra: Any) -> Dict[str, Any]:
    """构建标准错误响应体。"""
    body: Dict[str, Any] = {"success": False, "error": code, "message": message}
    body.update(extra)
    return body


def sse_event(event_type: str, **payload: Any) -> str:
    """把单个 SSE ``data:`` 行格式化为 JSON。"""
    data = {"type": event_type, **payload}
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_error(message: str) -> str:
    """格式化 SSE 错误事件。"""
    return sse_event("error", message=message)


# ---------------------------------------------------------------------------
# 异常处理器
# ---------------------------------------------------------------------------
async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    logger.warning(
        "api.error method=%s path=%s status=%s code=%s",
        request.method, request.url.path, exc.status_code, exc.code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body("HTTP_ERROR", str(exc.detail)),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "api.unhandled method=%s path=%s error=%s",
        request.method, request.url.path, exc,
    )
    return JSONResponse(
        status_code=500,
        content=error_body("INTERNAL_ERROR", str(exc)),
    )


def register_exception_handlers(app) -> None:
    """把统一异常处理器挂载到 FastAPI 应用。"""
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


__all__ = [
    "SSE_DONE",
    "SSE_EVENT_TYPES",
    "APIError",
    "error_body",
    "sse_event",
    "sse_error",
    "register_exception_handlers",
]
