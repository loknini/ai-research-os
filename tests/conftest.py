"""后端 pytest 共享夹具。"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RunIsolatedCase = Callable[[str, float], subprocess.CompletedProcess[str]]
_ASYNC_SHUTDOWN_ERRORS = (
    "Exception in thread",
    "RuntimeError: Event loop is closed",
)


@pytest.fixture
def project_root() -> Path:
    """返回仓库根目录，供源码契约与 CLI 测试复用。"""
    return PROJECT_ROOT


@dataclass(frozen=True)
class IsolatedRuntime:
    root: Path
    data_dir: Path
    log_dir: Path


@pytest.fixture
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> IsolatedRuntime:
    """为单个 pytest item 建立隔离的数据、日志和 UTF-8 环境。"""
    data_dir = tmp_path / "data"
    log_dir = tmp_path / "logs"
    data_dir.mkdir()
    log_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    monkeypatch.setenv("PYTHONUTF8", "1")
    return IsolatedRuntime(root=tmp_path, data_dir=data_dir, log_dir=log_dir)


@pytest.fixture
def app_client(isolated_runtime: IsolatedRuntime) -> Iterator[object]:
    """提供绑定隔离数据库的 FastAPI TestClient，并完整执行 lifespan。"""
    from fastapi.testclient import TestClient
    from scripts import database

    database.configure_paths(
        data_dir=isolated_runtime.data_dir,
        db_path=isolated_runtime.data_dir / "ai_research_os.db",
    )
    from backend.server.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def run_isolated_case(isolated_runtime: IsolatedRuntime) -> RunIsolatedCase:
    """在隔离子进程中运行一个迁移后的复杂回归实现。

    旧 QA 涉及模块级环境变量、SQLite 路径、logging handler 和 Windows
    multiprocessing；保留进程隔离可以避免 pytest 收集进程被污染。失败时统一
    附带 stdout/stderr，并把退出码为 0 的异步关闭异常视为失败，防止假绿。
    """

    def run(module: str, timeout: float = 300) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        try:
            result = subprocess.run(
                [sys.executable, "-m", module],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            pytest.fail(f"{module} 超过 {timeout:.0f}s 未完成：{exc}", pytrace=False)

        combined_output = f"{result.stdout}\n{result.stderr}"
        shutdown_error = next(
            (pattern for pattern in _ASYNC_SHUTDOWN_ERRORS if pattern in combined_output),
            None,
        )
        if result.returncode != 0 or shutdown_error:
            reason = (
                f"退出码 {result.returncode}"
                if result.returncode != 0
                else f"检测到异步关闭异常：{shutdown_error}"
            )
            pytest.fail(
                f"{module} 失败（{reason}）\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}",
                pytrace=False,
            )
        return result

    return run
