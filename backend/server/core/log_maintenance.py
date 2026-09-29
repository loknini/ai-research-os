"""日志目录布局、归档和清理工具。

运行期日志按 PID 分文件，避免多进程在 Windows 上同时写入或轮转同一个文件。
进程退出后再把对应文件移动到按日期划分的归档目录，从而兼顾写入安全与运维可读性。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_KINDS = ("app", "access", "error")
_PID_LOG_RE = re.compile(r"^(app|access|error)\.(\d+)\.log(?:\..+)?$")
_LAUNCHER_LOG_RE = re.compile(r"^(backend|frontend)(?:\.err)?\.log(?:\.\d+)?$")


@dataclass(frozen=True)
class LogLayout:
    root: Path
    launcher: Path
    runtime: Path
    archive: Path
    state: Path

    def kind_dir(self, kind: str) -> Path:
        if kind not in LOG_KINDS:
            raise ValueError(f"未知日志类型: {kind}")
        return self.runtime / kind


def resolve_log_root(log_dir: Optional[Path | str] = None) -> Path:
    """把日志目录统一解析为绝对路径；相对路径始终相对项目根目录。"""
    configured = Path(log_dir or os.environ.get("LOG_DIR") or PROJECT_ROOT / "logs")
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


def prepare_layout(log_dir: Optional[Path | str] = None) -> LogLayout:
    """创建并返回唯一正式日志目录布局。"""
    root = resolve_log_root(log_dir)
    layout = LogLayout(
        root=root,
        launcher=root / "launcher",
        runtime=root / "runtime",
        archive=root / "archive",
        state=root / "state",
    )
    for path in (layout.root, layout.launcher, layout.archive, layout.state):
        path.mkdir(parents=True, exist_ok=True)
    for kind in LOG_KINDS:
        layout.kind_dir(kind).mkdir(parents=True, exist_ok=True)
    return layout


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        # GetExitCodeProcess 只依赖标准库 ctypes，避免为了日志维护引入 psutil。
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_process_started_at(pid: int) -> Optional[float]:
    """读取 Windows 进程创建时间，用于识别已经被系统复用的 PID。"""
    if os.name != "nt" or pid <= 0:
        return None

    class FileTime(ctypes.Structure):
        _fields_ = (("low", ctypes.c_ulong), ("high", ctypes.c_ulong))

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        creation = FileTime()
        exit_time = FileTime()
        kernel_time = FileTime()
        user_time = FileTime()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        windows_ticks = (creation.high << 32) | creation.low
        return windows_ticks / 10_000_000 - 11_644_473_600
    finally:
        kernel32.CloseHandle(handle)


def _is_live_current_log(path: Path, pid: int) -> bool:
    """仅把仍在运行进程当前写入的基础 .log 文件视为受保护文件。"""
    if not path.name.endswith(".log"):
        return False
    try:
        # 很旧的同 PID 文件更可能是 PID 复用，不能永久阻止其归档。
        modified_at = path.stat().st_mtime
        if time.time() - modified_at > 2 * 86400:
            return False
    except OSError:
        return False
    started_at = _windows_process_started_at(pid)
    if started_at is not None and started_at > modified_at + 2:
        return False
    return _pid_is_running(pid)


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    index = 1
    while True:
        candidate = path.with_name(f"{path.name}.{index}")
        if not candidate.exists():
            return candidate
        index += 1


def _archive_path(layout: LogLayout, kind: str, source: Path) -> Path:
    try:
        modified = source.stat().st_mtime
    except OSError:
        modified = time.time()
    day = datetime.fromtimestamp(modified).strftime("%Y-%m-%d")
    target_dir = layout.archive / day / kind
    target_dir.mkdir(parents=True, exist_ok=True)
    return _unique_destination(target_dir / source.name)


def _iter_pid_logs(layout: LogLayout) -> Iterable[tuple[str, int, Path]]:
    for kind in LOG_KINDS:
        for path in layout.kind_dir(kind).glob(f"{kind}.*.log*"):
            match = _PID_LOG_RE.match(path.name)
            if path.is_file() and match:
                yield kind, int(match.group(2)), path
    # 兼容迁移旧版直接散落在 logs/ 根目录的运行日志。
    for path in layout.root.iterdir():
        match = _PID_LOG_RE.match(path.name)
        if path.is_file() and match:
            yield match.group(1), int(match.group(2)), path


def _read_pid(path: Path) -> Optional[int]:
    try:
        value = int(path.read_text(encoding="ascii").strip())
        return value if value > 0 else None
    except (OSError, ValueError):
        return None


def migrate_legacy_launcher_files(layout: LogLayout) -> int:
    """迁移旧版根目录启动器日志和 PID 文件；运行中的日志暂不移动。"""
    moved = 0
    service_pids: dict[str, Optional[int]] = {}
    for service in ("backend", "frontend"):
        legacy_pid = layout.root / f"{service}.pid"
        state_pid = layout.state / f"{service}.pid"
        pid = _read_pid(state_pid) or _read_pid(legacy_pid)
        service_pids[service] = pid
        if legacy_pid.exists() and not state_pid.exists():
            try:
                legacy_pid.replace(state_pid)
                moved += 1
            except OSError:
                pass

    for source in list(layout.root.iterdir()):
        match = _LAUNCHER_LOG_RE.match(source.name)
        if not source.is_file() or not match:
            continue
        pid = service_pids.get(match.group(1))
        if pid and _pid_is_running(pid):
            continue
        try:
            shutil.move(str(source), str(_unique_destination(layout.launcher / source.name)))
            moved += 1
        except (FileNotFoundError, PermissionError, OSError):
            pass
    return moved


def cleanup_stale_state_files(layout: LogLayout) -> int:
    """删除已退出服务或 PID 已被其他新进程复用的状态文件。"""
    removed = 0
    for path in layout.state.glob("*.pid"):
        pid = _read_pid(path)
        stale = pid is None or not _pid_is_running(pid)
        if not stale and pid is not None:
            started_at = _windows_process_started_at(pid)
            try:
                written_at = path.stat().st_mtime
            except OSError:
                written_at = time.time()
            stale = started_at is not None and started_at > written_at + 2
        if stale:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def archive_inactive_logs(log_dir: Optional[Path | str] = None) -> dict[str, int]:
    """归档已退出进程的运行日志，并迁移旧版平铺文件。"""
    layout = prepare_layout(log_dir)
    counts = {kind: 0 for kind in LOG_KINDS}
    for kind, pid, source in list(_iter_pid_logs(layout)):
        if _is_live_current_log(source, pid):
            continue
        try:
            shutil.move(str(source), str(_archive_path(layout, kind, source)))
            counts[kind] += 1
        except (FileNotFoundError, PermissionError, OSError):
            # 多 Worker 同时启动时可能竞争归档同一旧文件；失败不影响服务启动。
            continue
    counts["launcher"] = migrate_legacy_launcher_files(layout)
    counts["state"] = cleanup_stale_state_files(layout)
    return counts


def _all_managed_log_files(layout: LogLayout) -> list[Path]:
    files: list[Path] = []
    for root in (layout.launcher, layout.runtime, layout.archive):
        if root.exists():
            files.extend(path for path in root.rglob("*") if path.is_file())
    return files


def _protected_runtime_files(layout: LogLayout) -> set[Path]:
    protected: set[Path] = set()
    for _kind, pid, path in _iter_pid_logs(layout):
        if path.is_relative_to(layout.runtime) and _is_live_current_log(path, pid):
            protected.add(path)
    return protected


def _remove_empty_archive_dirs(layout: LogLayout) -> None:
    directories = sorted(
        (path for path in layout.archive.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in directories:
        try:
            path.rmdir()
        except OSError:
            pass


def prune_logs(
    log_dir: Optional[Path | str] = None,
    *,
    retention_days: int = 30,
    max_files: int = 500,
) -> dict[str, int]:
    """按保留天数和文件总数双重清理，不删除活跃进程正在写入的文件。"""
    layout = prepare_layout(log_dir)
    retention_days = max(1, int(retention_days))
    max_files = max(1, int(max_files))
    cutoff = time.time() - retention_days * 86400
    protected = _protected_runtime_files(layout)
    removed_expired = 0
    removed_excess = 0

    for path in _all_managed_log_files(layout):
        if path in protected:
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed_expired += 1
        except (FileNotFoundError, PermissionError, OSError):
            continue

    remaining = _all_managed_log_files(layout)
    if len(remaining) > max_files:
        removable = sorted(
            (path for path in remaining if path not in protected),
            key=lambda path: path.stat().st_mtime if path.exists() else float("inf"),
        )
        for path in removable:
            if len(remaining) - removed_excess <= max_files:
                break
            try:
                path.unlink()
                removed_excess += 1
            except (FileNotFoundError, PermissionError, OSError):
                continue

    _remove_empty_archive_dirs(layout)
    return {"expired": removed_expired, "excess": removed_excess}


def maintain_logs(
    log_dir: Optional[Path | str] = None,
    *,
    retention_days: int = 30,
    max_files: int = 500,
) -> dict[str, object]:
    """执行完整启动/停止维护：归档退出进程日志，再进行双重清理。"""
    layout = prepare_layout(log_dir)
    archived = archive_inactive_logs(layout.root)
    removed = prune_logs(
        layout.root,
        retention_days=retention_days,
        max_files=max_files,
    )
    return {
        "log_dir": str(layout.root),
        "archived": archived,
        "removed": removed,
    }


def _positive_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="维护 AI-Research-OS 日志目录")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("prepare", "archive", "cleanup", "layout"),
        default="prepare",
    )
    parser.add_argument("--log-dir", default=None, help="日志根目录，默认读取 LOG_DIR")
    parser.add_argument("--retention-days", type=int, default=None)
    parser.add_argument("--max-files", type=int, default=None)
    args = parser.parse_args(argv)

    layout = prepare_layout(args.log_dir)
    if args.command == "layout":
        result: object = {
            "root": str(layout.root),
            "launcher": str(layout.launcher),
            "runtime": str(layout.runtime),
            "archive": str(layout.archive),
            "state": str(layout.state),
        }
    elif args.command == "archive":
        result = {"log_dir": str(layout.root), "archived": archive_inactive_logs(layout.root)}
    elif args.command == "cleanup":
        result = {
            "log_dir": str(layout.root),
            "removed": prune_logs(
                layout.root,
                retention_days=args.retention_days or _positive_env("LOG_RETENTION_DAYS", 30),
                max_files=args.max_files or _positive_env("LOG_MAX_FILES", 500),
            ),
        }
    else:
        result = maintain_logs(
            layout.root,
            retention_days=args.retention_days or _positive_env("LOG_RETENTION_DAYS", 30),
            max_files=args.max_files or _positive_env("LOG_MAX_FILES", 500),
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LOG_KINDS",
    "LogLayout",
    "archive_inactive_logs",
    "cleanup_stale_state_files",
    "maintain_logs",
    "migrate_legacy_launcher_files",
    "prepare_layout",
    "prune_logs",
    "resolve_log_root",
]
