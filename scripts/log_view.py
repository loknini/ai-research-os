#!/usr/bin/env python3
"""统一查看和跟踪 AI-Research-OS 日志。

示例：
    python -m scripts.log_view --kind app --lines 100
    python -m scripts.log_view --kind error --follow
    python -m scripts.log_view --kind all --include-archive
"""
from __future__ import annotations

import argparse
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from backend.server.core.log_maintenance import LOG_KINDS, LogLayout, prepare_layout


VIEW_KINDS = (*LOG_KINDS, "backend", "frontend", "all")


def _runtime_files(layout: LogLayout, kind: str) -> list[Path]:
    return sorted(
        (path for path in layout.kind_dir(kind).glob(f"{kind}.*.log*") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )


def _launcher_files(layout: LogLayout, service: str) -> list[Path]:
    return sorted(
        (path for path in layout.launcher.glob(f"{service}*.log*") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )


def discover_logs(
    layout: LogLayout,
    kind: str,
    *,
    include_archive: bool = False,
) -> list[Path]:
    """按类别发现日志，调用方无需关心 Worker PID。"""
    files: list[Path] = []
    runtime_kinds = LOG_KINDS if kind == "all" else ((kind,) if kind in LOG_KINDS else ())
    for runtime_kind in runtime_kinds:
        files.extend(_runtime_files(layout, runtime_kind))
    launcher_kinds = ("backend", "frontend") if kind == "all" else ((kind,) if kind in ("backend", "frontend") else ())
    for launcher_kind in launcher_kinds:
        files.extend(_launcher_files(layout, launcher_kind))
    if include_archive and kind in (*LOG_KINDS, "all"):
        archive_kinds = LOG_KINDS if kind == "all" else (kind,)
        for archive_kind in archive_kinds:
            files.extend(
                path
                for path in layout.archive.glob(f"*/{archive_kind}/{archive_kind}.*.log*")
                if path.is_file()
            )
    return sorted(set(files), key=lambda path: path.stat().st_mtime)


def _tail(path: Path, count: int) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return list(deque(handle, maxlen=count))
    except OSError:
        return []


def _line_sort_key(path: Path, text: str) -> float:
    """优先按标准日志时间排序；无时间戳的原始输出回退到文件修改时间。"""
    timestamp = text[:23]
    for timestamp_format in ("%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(timestamp, timestamp_format).timestamp()
        except ValueError:
            continue
    return path.stat().st_mtime


def print_tail(files: list[Path], lines: int) -> None:
    """合并显示多个 PID 文件的尾部日志，并保留来源文件名。"""
    entries: list[tuple[float, str, str]] = []
    for path in files:
        for line in _tail(path, lines):
            text = line.rstrip("\r\n")
            entries.append((_line_sort_key(path, text), path.name, text))
    for _sort_key, name, text in sorted(entries)[-lines:]:
        print(f"[{name}] {text}")


def follow_logs(layout: LogLayout, kind: str, include_archive: bool) -> None:
    """持续跟踪现有及后续新建的 PID 日志文件。"""
    positions: dict[Path, int] = {}
    while True:
        files = discover_logs(layout, kind, include_archive=include_archive)
        pending: list[tuple[float, str, str]] = []
        for path in files:
            try:
                size = path.stat().st_size
                position = positions.get(path, size)
                if size < position:
                    position = 0
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(position)
                    for line in handle:
                        text = line.rstrip()
                        pending.append((_line_sort_key(path, text), path.name, text))
                    positions[path] = handle.tell()
            except (FileNotFoundError, PermissionError, OSError):
                positions.pop(path, None)
        for _sort_key, name, text in sorted(pending):
            print(f"[{name}] {text}", flush=True)
        time.sleep(0.5)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="统一查看 AI-Research-OS 日志")
    parser.add_argument("--kind", choices=VIEW_KINDS, default="all", help="日志类别")
    parser.add_argument("--lines", type=int, default=100, help="初始显示的总行数")
    parser.add_argument("--follow", action="store_true", help="持续跟踪新内容和新 PID 文件")
    parser.add_argument("--include-archive", action="store_true", help="同时查询历史归档")
    parser.add_argument("--log-dir", default=None, help="日志根目录，默认读取 LOG_DIR")
    args = parser.parse_args(argv)

    layout = prepare_layout(args.log_dir)
    files = discover_logs(layout, args.kind, include_archive=args.include_archive)
    if not files:
        print(f"没有找到 {args.kind} 日志：{layout.root}")
    else:
        print_tail(files, max(1, args.lines))
    if args.follow:
        try:
            follow_logs(layout, args.kind, args.include_archive)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["discover_logs", "follow_logs", "main", "print_tail"]
