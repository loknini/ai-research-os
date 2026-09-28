"""Stable Windows background entrypoint for the FastAPI backend.

The normal Uvicorn CLI treats ``SIGINT``/``SIGBREAK`` as shutdown requests.
That is desirable in an interactive terminal, but Windows IDE task runners can
send console-control events to descendants even when their windows are hidden.
For the detached ``start.ps1`` path we deliberately ignore those two console
signals and keep only Uvicorn's non-console termination handling.

This entrypoint is intentionally single-worker.  Uvicorn's Windows
multiprocess supervisor translates and rebroadcasts console signals to spawned
workers; a single async worker avoids that signal fan-out as well as needless
SQLite write-lock contention.  Interactive/manual launches remain free to use
the regular Uvicorn CLI with multiple workers.
"""

from __future__ import annotations

import argparse
import os
import signal
from collections.abc import Sequence

import uvicorn
from uvicorn import server as uvicorn_server


def configure_background_signals() -> None:
    """Ignore Windows console interrupts for the detached service process."""

    if os.name != "nt":
        return

    ignored = tuple(
        sig
        for name in ("SIGINT", "SIGBREAK")
        if (sig := getattr(signal, name, None)) is not None
    )
    for sig in ignored:
        signal.signal(sig, signal.SIG_IGN)

    # Server.capture_signals() otherwise replaces SIG_IGN when serving starts.
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
