#!/usr/bin/env python3
"""QA：标准库长期日志、分层目录、归档清理和请求 ID。"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from backend.server.core.logging import RequestIdMiddleware, configure_logging
from backend.server.core.log_maintenance import prepare_layout, prune_logs
from scripts.log_view import discover_logs, print_tail


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
    uvicorn_config_path = Path("backend/uvicorn-log-config.json")
    uvicorn_config = json.loads(uvicorn_config_path.read_text(encoding="utf-8"))
    uvicorn_formats = uvicorn_config["formatters"]
    windows_launcher = Path("start.ps1").read_text(encoding="utf-8-sig")
    posix_launcher = Path("start.sh").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="airos-logging-qa-") as tmp:
        log_dir = Path(tmp)
        layout = prepare_layout(log_dir)
        expired = log_dir / "app.99999999.log"
        expired.write_text("expired", encoding="utf-8")
        old = time.time() - 3 * 86400
        os.utime(expired, (old, old))
        inactive = log_dir / "access.99999998.log"
        inactive.write_text("inactive", encoding="utf-8")
        legacy_launcher = log_dir / "backend.log"
        legacy_launcher.write_text("legacy launcher", encoding="utf-8")

        with patch.dict(
            os.environ,
            {"LOG_LEVEL": "INFO", "LOG_RETENTION_DAYS": "1", "LOG_MAX_FILES": "20"},
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
        app_path = layout.kind_dir("app") / f"app.{pid}.log"
        error_path = layout.kind_dir("error") / f"error.{pid}.log"
        access_path = layout.kind_dir("access") / f"access.{pid}.log"
        app_text = app_path.read_text(encoding="utf-8")
        error_text = error_path.read_text(encoding="utf-8")
        access_text = access_path.read_text(encoding="utf-8")
        response_headers = dict(messages[0]["headers"])
        inactive_archived = not inactive.exists() and any(
            layout.archive.glob("*/access/access.99999998.log")
        )
        launcher_migrated = not legacy_launcher.exists() and (
            layout.launcher / "backend.log"
        ).exists()

        # 多 PID 文件必须按日志中的时间而非文件枚举顺序合并，保证排障时间轴稳定。
        timeline_a = log_dir / "timeline-a.log"
        timeline_b = log_dir / "timeline-b.log"
        timeline_raw = log_dir / "timeline-raw.log"
        timeline_a.write_text("2026-09-29 10:00:02,000 INFO later\n", encoding="utf-8")
        timeline_b.write_text("2026-09-29 10:00:01,000 INFO earlier\n", encoding="utf-8")
        timeline_raw.write_text("raw middle\n", encoding="utf-8")
        raw_timestamp = datetime(2026, 9, 29, 10, 0, 1, 500000).timestamp()
        os.utime(timeline_raw, (raw_timestamp, raw_timestamp))
        timeline_output = io.StringIO()
        with contextlib.redirect_stdout(timeline_output):
            print_tail([timeline_a, timeline_b, timeline_raw], 10)
        timeline_text = timeline_output.getvalue()

        # 当前进程的 3 个运行日志受保护；额外制造 4 个归档文件，验证总数上限。
        archive_dir = layout.archive / "2026-01-01" / "app"
        archive_dir.mkdir(parents=True, exist_ok=True)
        for index in range(4):
            archived = archive_dir / f"app.{90000000 + index}.log"
            archived.write_text(str(index), encoding="utf-8")
            os.utime(archived, (old + index, old + index))
        prune_result = prune_logs(log_dir, retention_days=3650, max_files=4)
        managed_count = sum(
            1
            for root in (layout.launcher, layout.runtime, layout.archive)
            for path in root.rglob("*")
            if path.is_file()
        )

        checks = {
            "launcher timestamp config": all(
                "%(asctime)s" in uvicorn_formats[name]["fmt"]
                and "%(msecs)03d" in uvicorn_formats[name]["fmt"]
                for name in ("default", "access")
            ),
            "frontend ansi disabled on windows": "NO_COLOR" in windows_launcher
            and "npm_config_color" in windows_launcher
            and "RemoveEnvironment @(\"FORCE_COLOR\")" in windows_launcher,
            "frontend ansi disabled on posix": "export NO_COLOR=1" in posix_launcher
            and "export npm_config_color=false" in posix_launcher
            and "unset FORCE_COLOR" in posix_launcher,
            "app log": "app-message" in app_text,
            "error split": "error-message" in error_text,
            "access split": "access-message" in access_text,
            "request id in access": "request_id=qa-request-123" in access_text,
            "request id in log": "request_id=qa-request-123" in app_text,
            "request id response": response_headers.get(b"x-request-id") == b"qa-request-123",
            "expired cleanup": not expired.exists(),
            "runtime layout": app_path.exists() and error_path.exists() and access_path.exists(),
            "inactive archive": inactive_archived,
            "launcher migration": launcher_migrated,
            "max file cleanup": prune_result["excess"] >= 1 and managed_count <= 4,
            "unified viewer discovery": app_path in discover_logs(layout, "app"),
            "unified viewer timeline": (
                timeline_text.index("earlier")
                < timeline_text.index("raw middle")
                < timeline_text.index("later")
            ),
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
