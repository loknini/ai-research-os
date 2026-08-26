"""Cron 调度器（Phase 4：定时任务自动化）。

设计要点
--------
* **多 Worker 安全**：调度器在每个 Worker 进程各跑一个 daemon 线程，每 60s 扫描
  ``cron_jobs`` 表找到期任务。领取和推进游标由一条带旧 ``next_run`` 快照条件的
  ``UPDATE`` 完成；多 Worker 并发时只有一个 ``rowcount=1``，旧快照不能重复领取。
* **零依赖 cron 解析**：自研 5 字段 cron 表达式解析器（分 时 日 月 周），
  支持 ``*``、``*/N``、``N-M``、``N,M``，以及 ``daily`` / ``weekly`` / ``hourly``
  语义快捷词。不引入 ``croniter`` 等第三方库。
* **多任务类型分派**：
  - ``command``  →  subprocess 执行 shell 命令（继承 SPACE_ID / DATA_DIR 环境变量）
  - ``agent_run`` →  调用 ``agent_runner.submit_run`` 触发多角色 Agent 管线
  - ``arxiv_fetch`` →  调用 ``fetch_arxiv.fetch_papers`` 抓取论文并落库
* **失败安全**：任何单个任务异常不会拖垮调度线程；每次执行结果写入
  ``cron_run_history`` 表供前端展示。
* **应用启动**：``main.py`` 的 lifespan 启动时调用 ``start_scheduler()``，
  应用关闭时线程随进程退出（daemon=True）。
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from . import config
from . import db

# ---------------------------------------------------------------------------
# 调度器配置
# ---------------------------------------------------------------------------
SCAN_INTERVAL = int(os.environ.get("CRON_SCAN_INTERVAL", "60"))  # 秒
SUBPROCESS_TIMEOUT = int(os.environ.get("CRON_SUBPROCESS_TIMEOUT", "120"))
JOB_NAME = "cron-scheduler"

_scheduler_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def start_scheduler() -> None:
    """启动调度器守护线程（幂等：已启动则跳过）。"""
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return
    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop, name=JOB_NAME, daemon=True
    )
    _scheduler_thread.start()
    print(f"[cron_scheduler] started (scan_interval={SCAN_INTERVAL}s)")


def stop_scheduler() -> None:
    """通知调度器停止（用于测试 / 优雅关闭）。"""
    _stop_event.set()


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------
def _scheduler_loop() -> None:
    """调度器主循环：在独立线程 + 自建事件循环中运行。"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # 启动时立即初始化一次 next_run（为没有 next_run 的任务计算）
        loop.run_until_complete(_init_next_runs())
        while not _stop_event.is_set():
            try:
                loop.run_until_complete(_scan_and_dispatch())
            except Exception as exc:  # noqa: BLE001
                print(f"[cron_scheduler] scan error: {exc}")
            _stop_event.wait(SCAN_INTERVAL)
    finally:
        loop.close()
    print("[cron_scheduler] stopped")


async def _init_next_runs() -> None:
    """为所有已启用但 next_run 为空的任务初始化下次执行时间。"""
    try:
        jobs = await db.database.get_all_cron_jobs()
        now_ms = int(time.time() * 1000)
        for job in jobs:
            if not job.get("next_run"):
                next_ms = compute_next_run(job["schedule"], now_ms)
                if next_ms:
                    await db.database.init_cron_next_run(job["id"], next_ms)
    except Exception as exc:  # noqa: BLE001
        print(f"[cron_scheduler] init next_runs error: {exc}")


async def _scan_and_dispatch() -> None:
    """扫描到期任务，抢锁后分派执行。"""
    now_ms = int(time.time() * 1000)
    due_jobs = await db.database.get_due_cron_jobs(now_ms)
    if not due_jobs:
        return

    for job in due_jobs:
        expected_next_run = int(job["next_run"])
        next_ms = compute_next_run(job["schedule"], now_ms)
        acquired = await db.database.try_acquire_cron_job(
            job["id"],
            job.get("space_id") or "__default__",
            expected_next_run,
            now_ms,
            next_ms or (now_ms + 3600000),
        )
        if not acquired:
            continue  # 另一个 Worker 已原子推进该次调度

        # 分派执行（异常不外泄）
        await dispatch_job(job)


# ---------------------------------------------------------------------------
# 任务分派
# ---------------------------------------------------------------------------
async def dispatch_job(
    job: Dict[str, Any],
    space_id: Optional[str] = None,
) -> Tuple[str, str]:
    """Execute one job through the canonical dispatcher and persist history."""
    job_id = job["id"]
    resolved_space_id = space_id or job.get("space_id") or "__default__"
    run_id = str(uuid.uuid4())
    started_at = int(time.time() * 1000)

    try:
        status, output = await execute_job(job, resolved_space_id)
    except Exception as exc:  # noqa: BLE001
        status = "error"
        output = f"dispatch error: {exc}"

    finished_at = int(time.time() * 1000)
    duration_ms = finished_at - started_at

    await db.database.add_cron_run_history(
        run_id, job_id, resolved_space_id, status, output[:4000],
        started_at, finished_at, duration_ms,
    )
    return status, output


async def execute_job(job: Dict[str, Any], space_id: str) -> Tuple[str, str]:
    """Run a job without changing scheduling metadata or writing history."""
    job_type = job.get("job_type") or job.get("jobType") or "command"
    if job_type == "command":
        return await _exec_command(job, space_id)
    if job_type == "agent_run":
        return await _exec_agent_run(job, space_id)
    if job_type == "arxiv_fetch":
        return await _exec_arxiv_fetch(job, space_id)
    return "error", f"unknown job_type: {job_type}"


def _parse_payload(job: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    raw = job.get("payload")
    if raw in (None, ""):
        return {}, None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, f"invalid JSON payload: {exc.msg}"
    if not isinstance(raw, dict):
        return None, "payload must be a JSON object"
    return raw, None


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> Tuple[Optional[int], Optional[str]]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, f"{name} must be an integer"
    if not minimum <= parsed <= maximum:
        return None, f"{name} must be between {minimum} and {maximum}"
    return parsed, None


async def _exec_command(job: Dict[str, Any], space_id: str) -> Tuple[str, str]:
    """执行 command 类型任务（subprocess，继承空间环境变量）。"""
    command = job.get("command") or ""
    if not command.strip():
        return "error", "empty command"

    env = os.environ.copy()
    env["SPACE_ID"] = space_id
    env["DATA_DIR"] = str(config.DATA_DIR)

    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
            env=env,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        status = "success" if proc.returncode == 0 else "failed"
        return status, output
    except subprocess.TimeoutExpired:
        return "timeout", f"command timed out after {SUBPROCESS_TIMEOUT}s"
    except Exception as exc:
        return "error", f"command error: {exc}"


async def _exec_agent_run(job: Dict[str, Any], space_id: str) -> Tuple[str, str]:
    """执行 agent_run 类型任务（触发多角色 Agent 管线）。

    payload 示例：{"requirement": "...", "roles": ["architect","planner"]}
    """
    from . import agent_runner

    payload, payload_error = _parse_payload(job)
    if payload_error or payload is None:
        return "error", payload_error or "invalid payload"

    requirement = payload.get("requirement") or job.get("description") or ""
    if not requirement:
        return "error", "agent_run payload missing 'requirement'"

    roles = payload.get("roles")
    if roles is not None and (
        not isinstance(roles, list) or not all(isinstance(role, str) and role for role in roles)
    ):
        return "error", "agent_run payload 'roles' must be a list of role names"
    run_id = await agent_runner.submit_run(space_id, requirement, roles=roles)
    return "success", f"agent run submitted: {run_id}"


async def _exec_arxiv_fetch(job: Dict[str, Any], space_id: str) -> Tuple[str, str]:
    """执行 arxiv_fetch 类型任务（抓取论文并落库）。

    payload 示例：{"query": "cat:cs.CV", "keywords": ["diffusion"], "max": 10}
    """
    from scripts.fetch_arxiv import fetch_papers

    payload, payload_error = _parse_payload(job)
    if payload_error or payload is None:
        return "error", payload_error or "invalid payload"

    search_query = payload.get("query") or "cat:cs.CV"
    keywords = payload.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [part.strip() for part in keywords.split(",") if part.strip()]
    if not isinstance(keywords, list) or not all(isinstance(keyword, str) for keyword in keywords):
        return "error", "arxiv_fetch payload 'keywords' must be a string list"
    max_results, max_error = _bounded_int(payload.get("max", 10), "max", 1, 100)
    days, days_error = _bounded_int(payload.get("days", 1), "days", 1, 365)
    if max_error or days_error or max_results is None or days is None:
        return "error", max_error or days_error or "invalid arXiv parameters"

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    papers = await asyncio.to_thread(
        fetch_papers,
        search_query=search_query,
        keywords=keywords if keywords else None,
        start_date=start_date.strftime("%Y%m%d"),
        end_date=end_date.strftime("%Y%m%d"),
        max_results=max_results,
    )

    if not papers:
        return "success", "no papers found"

    # 落库（去重）
    new_count = 0
    for paper in papers:
        existing = await db.database.get_paper_by_arxiv(paper["arxivId"], space_id=space_id)
        if not existing:
            if await db.database.insert_paper(paper, space_id=space_id):
                new_count += 1

    return "success", f"fetched {len(papers)} papers, {new_count} new (skipped {len(papers) - new_count} dups)"


# ---------------------------------------------------------------------------
# Cron 表达式解析器（零依赖，自研）
# ---------------------------------------------------------------------------
# 5 字段：minute hour day-of-month month day-of-week(0=Sun..6=Sat, 7=Sun)
# 支持语法：*  */N  N  N-M  N,M  （可组合，如 1,3,5）
# 语义快捷词：daily→"0 8 * * *"  weekly→"0 8 * * 1"  hourly→"0 * * * *"

_KEYWORD_MAP = {
    "daily": "0 8 * * *",
    "weekly": "0 8 * * 1",
    "hourly": "0 * * * *",
    "every_minute": "* * * * *",
}


def _parse_field(expr: str, min_val: int, max_val: int) -> List[int]:
    """解析单个 cron 字段为值列表。"""
    if expr == "*":
        return list(range(min_val, max_val + 1))

    values: set = set()
    for part in expr.split(","):
        part = part.strip()
        # */N
        if part.startswith("*/"):
            try:
                step = int(part[2:])
            except ValueError:
                continue
            if step <= 0:
                continue
            values.update(range(min_val, max_val + 1, step))
        # N-M
        elif "-" in part:
            try:
                lo, hi = part.split("-", 1)
                lo, hi = int(lo), int(hi)
            except ValueError:
                continue
            if lo > hi:
                lo, hi = hi, lo
            values.update(range(lo, hi + 1))
        # N 或 N/M
        elif "/" in part and not part.startswith("*"):
            # 如 2/15（从 2 开始每 15）→ 简化为 N
            try:
                base = int(part.split("/")[0])
            except ValueError:
                continue
            values.add(base)
        else:
            try:
                val = int(part)
            except ValueError:
                continue
            if min_val <= val <= max_val:
                values.add(val)
    return sorted(values)


def compute_next_run(schedule: str, after_ms: int) -> Optional[int]:
    """计算 schedule 表达式下一次执行时间（毫秒戳）。

    ``after_ms`` 为当前时间戳。返回下一个匹配时间点（> after）的毫秒戳，
    或 None 表示无法解析。
    """
    if not schedule:
        return None

    expr = schedule.strip().lower()
    if expr in _KEYWORD_MAP:
        expr = _KEYWORD_MAP[expr]

    parts = expr.split()
    if len(parts) != 5:
        return None

    minutes = _parse_field(parts[0], 0, 59)
    hours = _parse_field(parts[1], 0, 23)
    days = _parse_field(parts[2], 1, 31)
    months = _parse_field(parts[3], 1, 12)
    dow = _parse_field(parts[4], 0, 7)  # 0 和 7 都是周日

    if not all([minutes, hours, days, months, dow]):
        return None

    # 0 和 7 统一为周日（7→0）
    if 7 in dow:
        dow = sorted(set(d if d != 7 else 0 for d in dow))

    after = datetime.fromtimestamp(after_ms / 1000.0)
    # 从下一分钟开始逐分钟搜索（最多扫 366 天避免死循环）
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    max_iter = 366 * 24 * 60  # 一年内的分钟数
    for _ in range(max_iter):
        if (
            candidate.minute in minutes
            and candidate.hour in hours
            and candidate.day in days
            and candidate.month in months
            and (candidate.weekday() + 1) % 7 in dow  # Python weekday: Mon=0..Sun=6 → 转 0=Sun
        ):
            return int(candidate.timestamp() * 1000)
        candidate += timedelta(minutes=1)

    return None


__all__ = [
    "start_scheduler",
    "stop_scheduler",
    "compute_next_run",
    "dispatch_job",
    "execute_job",
]
