"""跨端口重复后端实例检测（心跳文件）。

背景：start.ps1 只能发现**同端口**残留；两个不同端口的后端共享同一 SQLite
会造成慢性锁竞争（reindex 500 的事故根因）。本模块用心跳文件做跨端口可见性：

* 每个 uvicorn supervisor（worker 的 ppid 即 supervisor pid）在 lifespan 启动时
  登记并每 30s 刷新一次心跳；同 supervisor 的 workers 共用一条记录；
* 判定死亡双条件（满足任一即修剪）：心跳超 120s 未更新，或记录的 pid 已不存在
  —— 重启场景（旧 supervisor 刚被杀、心跳仍新鲜）靠 pid 存活校验消除误报；
* 发现同 DB 下有**其它 supervisor** 的新鲜心跳 → lifespan 打 ERROR 日志，
  ``/api/healthz`` 暴露 ``siblingInstances``，start.ps1 预检直接 abort。

只做可见性 + 启动期拦截，不做强制单例（避免误杀合法场景）；文件原子写
（tmp + replace），多进程并发安全。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List

from scripts.process_utils import pid_is_running

_HEARTBEAT_FILE = ".backend_supervisors.json"
_LOCK_FILE = ".backend_supervisors.lock"
_BEAT_INTERVAL_SEC = 30
_STALE_AFTER_SEC = 120


def _data_dir() -> Path:
    from . import config
    return config.DATA_DIR


def _heartbeat_path() -> Path:
    return _data_dir() / _HEARTBEAT_FILE


@contextmanager
def _heartbeat_lock(timeout: float = 0.5) -> Iterator[bool]:
    """跨进程短锁，避免多个 supervisor 的 read-modify-write 互相覆盖。"""
    path = _data_dir() / _LOCK_FILE
    deadline = time.monotonic() + timeout
    fd = None
    while time.monotonic() < deadline:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            break
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > 5:
                    path.unlink()
                    continue
            except OSError:
                pass
            time.sleep(0.02)
        except OSError:
            break
    try:
        yield fd is not None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                path.unlink()
            except OSError:
                pass


def supervisor_pid() -> int:
    """返回本实例稳定 PID：多 worker 取 supervisor，单进程取自身。

    单进程 uvicorn 的父进程通常是 PowerShell/bash，若一律取 ppid 会把终端误当
    后端；后端退出但终端仍活着时将持续误报。因此只有明确配置 workers>1 才取 ppid。
    """
    try:
        workers = 1
        argv = sys.argv or []
        for i, arg in enumerate(argv):
            if arg == "--workers" and i + 1 < len(argv):
                workers = int(argv[i + 1])
                break
            if arg.startswith("--workers="):
                workers = int(arg.split("=", 1)[1])
                break
        else:
            workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
        return os.getppid() if workers > 1 else os.getpid()
    except Exception:
        return os.getpid()


def detect_port() -> int:
    """尽力探测本实例监听端口：argv --port → APP_PORT → 8000。"""
    argv = sys.argv or []
    for i, arg in enumerate(argv):
        if arg == "--port" and i + 1 < len(argv):
            try:
                return int(argv[i + 1])
            except ValueError:
                pass
        if arg.startswith("--port="):
            try:
                return int(arg.split("=", 1)[1])
            except ValueError:
                pass
    try:
        return int(os.environ.get("APP_PORT", "8000"))
    except ValueError:
        return 8000


def _read_all() -> Dict[str, Any]:
    path = _heartbeat_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write_all(entries: Dict[str, Any]) -> None:
    path = _heartbeat_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


def _prune(entries: Dict[str, Any], now_ms: int) -> Dict[str, Any]:
    """剔除死亡 supervisor 记录：心跳超期，或 pid 已不存在（重启误报消除）。"""
    fresh: Dict[str, Any] = {}
    for pid, info in entries.items():
        try:
            if not isinstance(info, dict):
                continue
            if (now_ms - int(info.get("updatedAt", 0))) // 1000 > _STALE_AFTER_SEC:
                continue
            try:
                pid_int = int(pid)
            except (TypeError, ValueError):
                continue
            if not _pid_alive(pid_int):
                continue
            fresh[pid] = info
        except Exception:
            continue
    return fresh


_pid_alive = pid_is_running


def beat() -> Dict[str, Any]:
    """登记/刷新本 supervisor 心跳，返回修剪后的全量记录（含自己）。"""
    now_ms = int(time.time() * 1000)
    with _heartbeat_lock() as locked:
        if not locked:
            return _prune(_read_all(), now_ms)
        entries = _prune(_read_all(), now_ms)
        me = str(supervisor_pid())
        prev = entries.get(me)
        started = prev.get("startedAt", now_ms) if isinstance(prev, dict) else now_ms
        entries[me] = {"port": detect_port(), "startedAt": started, "updatedAt": now_ms}
        _write_all(entries)
        return entries


def list_siblings() -> List[Dict[str, Any]]:
    """列出同 DB 下其它 supervisor 的新鲜心跳（无则 []）。

    修剪结果写回文件（崩溃残留不堆积）；写回失败忽略，不影响返回值。
    """
    now_ms = int(time.time() * 1000)
    with _heartbeat_lock() as locked:
        entries = _prune(_read_all(), now_ms)
        if locked:
            _write_all(entries)
    me = str(supervisor_pid())
    out: List[Dict[str, Any]] = []
    for pid, info in entries.items():
        if pid != me and isinstance(info, dict):
            out.append({"supervisorPid": pid, **info})
    return out


async def heartbeat_loop(stop: asyncio.Event) -> None:
    """lifespan 后台任务：每 30s 刷新一次，直到 stop。"""
    while not stop.is_set():
        try:
            beat()
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=_BEAT_INTERVAL_SEC)
        except asyncio.TimeoutError:
            pass


__all__ = ["beat", "list_siblings", "heartbeat_loop", "supervisor_pid", "detect_port"]
