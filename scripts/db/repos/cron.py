"""Cron persistence repository."""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from ..core import (
    DEFAULT_SPACE,
    _clean_text_for_db,
    _fetchall,
    _fetchone,
    get_db,
    with_busy_retry,
)

def cron_job_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将 cron_jobs 行转换为前端契约的 camelCase 字典。"""
    return {
        'id': row['id'],
        'name': row['name'],
        'description': row['description'],
        'schedule': row['schedule'],
        'command': row['command'],
        'jobType': row['job_type'],
        'payload': json.loads(row['payload']) if row['payload'] else None,
        'enabled': bool(row['enabled']),
        'lastRun': row['last_run'],
        'nextRun': row['next_run'],
        'runCount': row['run_count'],
        'createdAt': row['created_at'],
    }


async def get_cron_jobs(space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间的定时任务列表。"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT * FROM cron_jobs WHERE space_id = ? ORDER BY created_at DESC', (space_id,))
        return [cron_job_to_dict(row) for row in rows]


async def create_cron_job(job: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> Dict[str, Any]:
    """在某空间创建定时任务。"""
    now = int(time.time() * 1000)
    job_id = job.get('id') or str(uuid.uuid4())
    job_type = job.get('jobType') or job.get('job_type') or 'command'
    payload = job.get('payload')
    payload_str = json.dumps(payload, ensure_ascii=False) if payload else None
    record = {
        'id': job_id,
        'name': job.get('name', ''),
        'description': job.get('description', ''),
        'schedule': job.get('schedule', ''),
        'command': job.get('command', ''),
        'jobType': job_type,
        'payload': payload,
        'enabled': bool(job.get('enabled', True)),
        'lastRun': None,
        'nextRun': None,
        'runCount': 0,
        'createdAt': job.get('createdAt', now),
    }
    try:
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO cron_jobs
                (id, name, description, schedule, command, job_type, payload, enabled, last_run, next_run, run_count, created_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record['id'], record['name'], record['description'], record['schedule'], record['command'],
                job_type, payload_str,
                1 if record['enabled'] else 0, record['lastRun'], record['nextRun'], record['runCount'],
                record['createdAt'], space_id))
        return record
    except Exception as e:
        print(f"Create cron job error: {e}")
        return {}


async def toggle_cron_job(job_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """切换某空间任务启用状态，返回更新后的任务；不存在返回 None。"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM cron_jobs WHERE id = ? AND space_id = ?', (job_id, space_id))
        if not row:
            return None
        new_enabled = 0 if row['enabled'] else 1
        await conn.execute('UPDATE cron_jobs SET enabled = ? WHERE id = ? AND space_id = ?',
                           (new_enabled, job_id, space_id))
        row = await _fetchone(conn, 'SELECT * FROM cron_jobs WHERE id = ? AND space_id = ?', (job_id, space_id))
        return cron_job_to_dict(row)


async def run_cron_job(job_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """标记某空间任务已运行（更新 lastRun / runCount），返回更新后的任务；不存在返回 None。"""
    now = int(time.time() * 1000)
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM cron_jobs WHERE id = ? AND space_id = ?', (job_id, space_id))
        if not row:
            return None
        await conn.execute(
            'UPDATE cron_jobs SET last_run = ?, run_count = run_count + 1 WHERE id = ? AND space_id = ?',
            (now, job_id, space_id))
        row = await _fetchone(conn, 'SELECT * FROM cron_jobs WHERE id = ? AND space_id = ?', (job_id, space_id))
        return cron_job_to_dict(row)


async def delete_cron_job(job_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某空间定时任务。"""
    try:
        async with get_db() as conn:
            cur = await conn.execute('DELETE FROM cron_jobs WHERE id = ? AND space_id = ?', (job_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete cron job error: {e}")
        return False


async def get_due_cron_jobs(now_ms: int) -> List[Dict[str, Any]]:
    """获取所有已到点、已启用且 next_run <= now 的任务（跨所有空间）。

    调度器每轮调用此函数扫描到期任务，再对每个任务做原子抢锁。
    """
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            'SELECT * FROM cron_jobs WHERE enabled = 1 AND next_run IS NOT NULL AND next_run <= ?',
            (now_ms,))
        return [dict(row) for row in rows]


async def try_acquire_cron_job(
    job_id: str,
    space_id: str,
    expected_next_run_ms: int,
    now_ms: int,
    following_next_run_ms: int,
) -> bool:
    """Atomically claim one due schedule occurrence and advance its cursor.

    ``expected_next_run_ms`` acts as the optimistic-lock token.  Updating the
    cursor in the same statement means a worker holding a stale due-job snapshot
    cannot claim the same occurrence after another worker has rescheduled it.
    """
    async with get_db() as conn:
        cur = await conn.execute(
            'UPDATE cron_jobs '
            'SET last_run = ?, next_run = ?, run_count = run_count + 1 '
            'WHERE id = ? AND space_id = ? AND enabled = 1 '
            'AND next_run = ? AND next_run <= ?',
            (
                now_ms, following_next_run_ms, job_id, space_id,
                expected_next_run_ms, now_ms,
            ),
        )
        return cur.rowcount > 0


async def update_cron_next_run(job_id: str, next_run_ms: int) -> None:
    """更新任务下次执行时间（调度器在抢锁成功后调用）。"""
    async with get_db() as conn:
        await conn.execute(
            'UPDATE cron_jobs SET next_run = ?, run_count = run_count + 1 WHERE id = ?',
            (next_run_ms, job_id))


async def init_cron_next_run(job_id: str, next_run_ms: int) -> None:
    """初始化任务的 next_run（创建或启用时调用）。"""
    async with get_db() as conn:
        await conn.execute(
            'UPDATE cron_jobs SET next_run = ? WHERE id = ?', (next_run_ms, job_id))


async def get_all_cron_jobs() -> List[Dict[str, Any]]:
    """获取所有空间的定时任务（调度器初始化时用，计算 next_run）。"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT * FROM cron_jobs WHERE enabled = 1 ORDER BY created_at')
        return [dict(row) for row in rows]


async def add_cron_run_history(
    run_id: str, cron_job_id: str, space_id: str, status: str,
    output: str, started_at: int, finished_at: int, duration_ms: int,
) -> None:
    """记录一次定时任务执行历史。"""
    async with get_db() as conn:
        await conn.execute(
            '''INSERT INTO cron_run_history
               (id, cron_job_id, space_id, status, output, started_at, finished_at, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (run_id, cron_job_id, space_id, status, output, started_at, finished_at, duration_ms))


async def get_cron_run_history(
    space_id: str = DEFAULT_SPACE,
    limit: int = 50,
    cron_job_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """获取某空间的定时任务执行历史（最近 N 条）。"""
    async with get_db() as conn:
        query = 'SELECT * FROM cron_run_history WHERE space_id = ?'
        params: List[Any] = [space_id]
        if cron_job_id:
            query += ' AND cron_job_id = ?'
            params.append(cron_job_id)
        query += ' ORDER BY started_at DESC LIMIT ?'
        params.append(limit)
        rows = await _fetchall(conn, query, tuple(params))
        return [dict(row) for row in rows]


__all__ = [
    "cron_job_to_dict",
    "get_cron_jobs",
    "create_cron_job",
    "toggle_cron_job",
    "run_cron_job",
    "delete_cron_job",
    "get_due_cron_jobs",
    "try_acquire_cron_job",
    "update_cron_next_run",
    "init_cron_next_run",
    "get_all_cron_jobs",
    "add_cron_run_history",
    "get_cron_run_history",
]
