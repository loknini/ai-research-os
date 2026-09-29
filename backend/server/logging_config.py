"""Long-lived application logging using only Python's standard library.

Each process writes its own files so interactive/production multi-worker runs
never race while rotating a shared file.  Files rotate at local midnight and
old files from exited processes are removed by retention age during startup.
"""
from __future__ import annotations

import contextvars
import logging
import os
import time
import uuid
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

from . import config

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "airos_request_id", default="-"
)
_configured_pid: Optional[int] = None
access_logger = logging.getLogger("airos.access")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class RequestIdMiddleware:
    """Pure ASGI middleware that adds a safe request ID to logs/responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        raw = headers.get(b"x-request-id", b"").decode("ascii", "ignore")
        request_id = raw[:64] if raw and raw.replace("-", "").isalnum() else uuid.uuid4().hex
        token = _request_id.set(request_id)
        started = time.monotonic()
        status_code = 500

        async def send_with_request_id(message):
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status") or 500)
                response_headers = list(message.get("headers") or [])
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            access_logger.info(
                "http.request method=%s path=%s status=%s duration_ms=%d",
                scope.get("method") or "-",
                scope.get("path") or "-",
                status_code,
                round((time.monotonic() - started) * 1000),
            )
            _request_id.reset(token)


def _positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _cleanup_expired_logs(log_dir: Path, retention_days: int) -> None:
    cutoff = time.time() - retention_days * 86400
    for pattern in ("app.*.log*", "error.*.log*", "access.*.log*"):
        for path in log_dir.glob(pattern):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                # Logging setup must never prevent the application from starting.
                pass


def _file_handler(path: Path, level: int, retention_days: int) -> logging.Handler:
    handler = TimedRotatingFileHandler(
        path,
        when="midnight",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8",
        delay=True,
    )
    handler.setLevel(level)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s pid=%(process)d thread=%(threadName)s "
        "request_id=%(request_id)s %(name)s: %(message)s"
    ))
    setattr(handler, "_airos_managed", True)
    return handler


def configure_logging(log_dir: Optional[Path] = None) -> Path:
    """Configure durable app/error logs once per process and return the directory."""
    global _configured_pid
    pid = os.getpid()
    configured_dir = Path(log_dir or os.environ.get("LOG_DIR") or config.PROJECT_ROOT / "logs")
    resolved = configured_dir if configured_dir.is_absolute() else config.PROJECT_ROOT / configured_dir
    if _configured_pid == pid:
        return resolved

    resolved.mkdir(parents=True, exist_ok=True)
    retention_days = _positive_int("LOG_RETENTION_DAYS", 30)
    _cleanup_expired_logs(resolved, retention_days)

    root = logging.getLogger()
    # A spawned/forked worker may inherit handlers from its parent. Only remove
    # handlers owned by this module; keep Uvicorn's console handler intact.
    for logger in (
        root,
        logging.getLogger("uvicorn"),
        logging.getLogger("uvicorn.access"),
        access_logger,
    ):
        for handler in list(logger.handlers):
            if getattr(handler, "_airos_managed", False):
                logger.removeHandler(handler)
                handler.close()

    level_name = (os.environ.get("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    app_handler = _file_handler(resolved / f"app.{pid}.log", level, retention_days)
    error_handler = _file_handler(resolved / f"error.{pid}.log", logging.ERROR, retention_days)
    access_handler = _file_handler(resolved / f"access.{pid}.log", level, retention_days)
    root.setLevel(min(level, logging.ERROR))
    root.addHandler(app_handler)
    root.addHandler(error_handler)

    # Uvicorn's loggers stop propagation, so explicitly attach the same durable
    # handlers while leaving its normal console handlers in place.
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.propagate = False
    uvicorn_logger.addHandler(app_handler)
    uvicorn_logger.addHandler(error_handler)
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_access_logger.propagate = False
    uvicorn_access_logger.addHandler(access_handler)
    request_logger = logging.getLogger("airos.access")
    request_logger.setLevel(level)
    request_logger.propagate = False
    request_logger.addHandler(access_handler)

    _configured_pid = pid
    logging.getLogger(__name__).info(
        "logging.ready directory=%s retention_days=%s", resolved, retention_days
    )
    return resolved


__all__ = ["RequestIdMiddleware", "configure_logging"]
