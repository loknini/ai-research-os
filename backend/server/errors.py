"""Shared error handling and SSE helpers.

All REST errors are returned as JSON ``{success: false, error, message}`` so the
frontend (which depends on this shape) keeps working.  SSE streaming endpoints
use the ``SSE_DONE`` sentinel and the ``sse_event`` / ``sse_error`` helpers.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------------------
# SSE constants
# ---------------------------------------------------------------------------
SSE_DONE = "[DONE]"
SSE_EVENT_TYPES = {"phase_start", "start", "progress", "complete", "error"}


class APIError(Exception):
    """Application-level error that maps to a JSON error body."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR", status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Response body helpers
# ---------------------------------------------------------------------------
def error_body(code: str, message: str, **extra: Any) -> Dict[str, Any]:
    """Build a standard error response body."""
    body: Dict[str, Any] = {"success": False, "error": code, "message": message}
    body.update(extra)
    return body


def sse_event(event_type: str, **payload: Any) -> str:
    """Format a single SSE ``data:`` line as JSON."""
    data = {"type": event_type, **payload}
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_error(message: str) -> str:
    """Format an SSE error event."""
    return sse_event("error", message=message)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------
async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
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
    return JSONResponse(
        status_code=500,
        content=error_body("INTERNAL_ERROR", str(exc)),
    )


def register_exception_handlers(app) -> None:
    """Attach the unified exception handlers to the FastAPI app."""
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
