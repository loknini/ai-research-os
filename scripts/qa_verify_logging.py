#!/usr/bin/env python3
"""QA: durable stdlib logging, retention cleanup, and request IDs."""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from backend.server.logging_config import RequestIdMiddleware, configure_logging


def _close_managed_handlers() -> None:
    seen: set[int] = set()
    for target in (
        logging.getLogger(),
        logging.getLogger("uvicorn"),
        logging.getLogger("uvicorn.access"),
        logging.getLogger("airos.access"),
    ):
        for handler in list(target.handlers):
            if not getattr(handler, "_airos_managed", False):
                continue
            target.removeHandler(handler)
            if id(handler) not in seen:
                seen.add(id(handler))
                handler.close()


async def _exercise_request_id() -> tuple[list[dict], list[dict]]:
    messages: list[dict] = []

    async def app(scope, receive, send):
        logging.getLogger("qa.request").info("inside-request")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = RequestIdMiddleware(app)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/qa",
        "headers": [(b"x-request-id", b"qa-request-123")],
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await middleware(scope, receive, send)
    return messages, scope["headers"]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="airos-logging-qa-") as tmp:
        log_dir = Path(tmp)
        expired = log_dir / "app.999999.log"
        expired.write_text("expired", encoding="utf-8")
        old = time.time() - 3 * 86400
        os.utime(expired, (old, old))

        with patch.dict(
            os.environ,
            {"LOG_LEVEL": "INFO", "LOG_RETENTION_DAYS": "1"},
            clear=False,
        ):
            configure_logging(log_dir)
            logging.getLogger("qa.app").info("app-message")
            logging.getLogger("qa.app").error("error-message")
            logging.getLogger("uvicorn.access").info("access-message")

            from backend.server import tool_registry
            from backend.server.skills_bridge import invoke_skill

            @tool_registry.register_tool(name="__qa_logging_tool")
            def _qa_tool(params, space_id=None):
                return {"success": True, "seen": bool(params), "space": space_id}

            tool_registry.execute(
                "__qa_logging_tool",
                {"api_key": "DO-NOT-LOG-THIS", "query": "private query"},
            )
            invoke_skill("demo_echo", {"input": "DO-NOT-LOG-THIS-EITHER"})
            messages, _ = asyncio.run(_exercise_request_id())

        _close_managed_handlers()

        pid = os.getpid()
        app_text = (log_dir / f"app.{pid}.log").read_text(encoding="utf-8")
        error_text = (log_dir / f"error.{pid}.log").read_text(encoding="utf-8")
        access_text = (log_dir / f"access.{pid}.log").read_text(encoding="utf-8")
        response_headers = dict(messages[0]["headers"])

        checks = {
            "app log": "app-message" in app_text,
            "error split": "error-message" in error_text,
            "access split": "access-message" in access_text,
            "request id in access": "request_id=qa-request-123" in access_text,
            "request id in log": "request_id=qa-request-123" in app_text,
            "request id response": response_headers.get(b"x-request-id") == b"qa-request-123",
            "expired cleanup": not expired.exists(),
            "tool lifecycle": "tool.start name=__qa_logging_tool" in app_text
            and "tool.complete name=__qa_logging_tool" in app_text,
            "skill lifecycle": "skill.start name=demo_echo" in app_text
            and "skill.complete name=demo_echo" in app_text,
            "tool values redacted": "DO-NOT-LOG" not in app_text and "private query" not in app_text,
        }
        for name, ok in checks.items():
            print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        failed = [name for name, ok in checks.items() if not ok]
        print(f"\nTOTAL: {len(checks)}  PASS: {len(checks) - len(failed)}  FAIL: {len(failed)}")
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
