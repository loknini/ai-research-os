"""仅使用 Python 标准库实现的长期应用日志。

每个进程写入独立文件，避免交互模式或生产多 Worker 在轮转共享文件时发生竞争。
日志按本地午夜轮转；启动时归档退出进程的日志，并按期限与文件数双重清理。
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
from .log_maintenance import maintain_logs, prepare_layout

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
    """为日志和响应添加安全请求 ID 的纯 ASGI 中间件。"""

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
    """每个进程只配置一次持久化应用/错误日志，并返回日志目录。"""
    global _configured_pid
    pid = os.getpid()
    configured_dir = Path(log_dir or os.environ.get("LOG_DIR") or config.PROJECT_ROOT / "logs")
    resolved = configured_dir if configured_dir.is_absolute() else config.PROJECT_ROOT / configured_dir
    if _configured_pid == pid:
        return resolved

    layout = prepare_layout(resolved)
    retention_days = _positive_int("LOG_RETENTION_DAYS", 30)
    max_files = _positive_int("LOG_MAX_FILES", 500)
    maintain_logs(
        layout.root,
        retention_days=retention_days,
        max_files=max_files,
    )

    root = logging.getLogger()
    # 派生 Worker 可能继承父进程的处理器；这里只移除本模块创建的处理器，
    # 保留 Uvicorn 自身的控制台处理器。
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
    app_handler = _file_handler(layout.kind_dir("app") / f"app.{pid}.log", level, retention_days)
    error_handler = _file_handler(
        layout.kind_dir("error") / f"error.{pid}.log",
        logging.ERROR,
        retention_days,
    )
    access_handler = _file_handler(
        layout.kind_dir("access") / f"access.{pid}.log",
        level,
        retention_days,
    )
    root.setLevel(min(level, logging.ERROR))
    root.addHandler(app_handler)
    root.addHandler(error_handler)

    # Uvicorn 日志器会停止向上传播，因此显式挂载同一组持久化处理器，
    # 同时保留其原有控制台处理器。
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
        "logging.ready directory=%s retention_days=%s max_files=%s",
        layout.root,
        retention_days,
        max_files,
    )
    return resolved


__all__ = ["RequestIdMiddleware", "configure_logging"]
