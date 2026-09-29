"""FastAPI 后端稳定的 Windows 后台入口。

常规 Uvicorn CLI 把 ``SIGINT``、``SIGBREAK`` 视为关闭请求，这适合交互终端；但
Windows IDE 任务运行器即使隐藏窗口，也可能向后代进程发送控制台事件。因此通过
``start.ps1`` 分离启动时会忽略这两个控制台信号，只保留 Uvicorn 的非控制台终止处理。

该入口有意使用单 Worker。Uvicorn 的 Windows 多进程监管器会转换并向子 Worker
重播控制台信号；单异步 Worker 既避免信号扩散，也减少不必要的 SQLite 写锁竞争。
交互或手动启动仍可使用常规 Uvicorn CLI 的多 Worker 模式。
"""

from __future__ import annotations

import argparse
import os
import signal
from collections.abc import Sequence

import uvicorn
from uvicorn import server as uvicorn_server


def configure_background_signals() -> None:
    """让分离运行的服务进程忽略 Windows 控制台中断。"""

    if os.name != "nt":
        return

    ignored = tuple(
        sig
        for name in ("SIGINT", "SIGBREAK")
        if (sig := getattr(signal, name, None)) is not None
    )
    for sig in ignored:
        signal.signal(sig, signal.SIG_IGN)

    # 否则 Server.capture_signals() 会在服务启动时覆盖 SIG_IGN。
    uvicorn_server.HANDLED_SIGNALS = tuple(
        sig for sig in uvicorn_server.HANDLED_SIGNALS if sig not in ignored
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run AI-Research-OS as a detached Windows service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_background_signals()
    uvicorn.run(
        "backend.server.main:app",
        host=args.host,
        port=args.port,
        workers=1,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
