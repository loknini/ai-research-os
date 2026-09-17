"""Tasks persistence repository."""
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

from .versions import create_version

def task_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将任务数据库行转换为字典"""
    return {
        'id': row['id'],
        'title': row['title'],
        'description': row['description'],
        'status': row['status'],
        'priority': row['priority'],
        'deadline': row['deadline'],
        'tags': json.loads(row['tags']) if row['tags'] else [],
        'projectId': row['project_id'],
        'parentTaskId': row['parent_task_id'],
        'aiSuggested': bool(row['ai_suggested']),
        'completedAt': row['completed_at'],
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }


async def get_all_tasks(space_id: str = DEFAULT_SPACE, project_id: Optional[str] = None,
                        status: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取某空间任务，支持按项目和状态筛选"""
    async with get_db() as conn:
        query = 'SELECT * FROM tasks WHERE space_id = ?'
        params: List[Any] = [space_id]
        if project_id:
            query += ' AND project_id = ?'
            params.append(project_id)
        if status:
            query += ' AND status = ?'
            params.append(status)
        query += ' ORDER BY priority DESC, created_at DESC'
        rows = await _fetchall(conn, query, params)
        return [task_to_dict(row) for row in rows]


async def get_task_by_id(task_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 ID 获取任务（按空间过滤）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM tasks WHERE id = ? AND space_id = ?', (task_id, space_id))
        return task_to_dict(row) if row else None


async def insert_task(task: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """向某空间插入新任务"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT INTO tasks
                (id, title, description, status, priority, deadline, tags,
                 project_id, parent_task_id, ai_suggested, completed_at, created_at, updated_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task['id'],
                task['title'],
                task.get('description', ''),
                task.get('status', 'todo'),
                task.get('priority', 'medium'),
                task.get('deadline'),
                json.dumps(task.get('tags', []), ensure_ascii=False),
                task.get('projectId'),
                task.get('parentTaskId'),
                1 if task.get('aiSuggested') else 0,
                task.get('completedAt'),
                task.get('createdAt', now),
                now,
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Insert task error: {e}")
        return False


async def update_task(task_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新某空间任务（先按空间取当前值生成版本，再按空间更新）"""
    try:
        async with get_db() as conn:
            allowed_fields = {
                'title', 'description', 'status', 'priority', 'deadline',
                'tags', 'projectId', 'parentTaskId', 'completedAt',
            }
            updates = {k: v for k, v in updates.items() if k in allowed_fields}
            if not updates:
                return False
            current_task = await get_task_by_id(task_id, space_id)
            if current_task:
                change_summary = ', '.join([f"{k}={v}" for k, v in updates.items()])
                await create_version('task', task_id, current_task, change_summary, space_id=space_id)
            field_mapping = {
                'projectId': 'project_id',
                'parentTaskId': 'parent_task_id',
                'completedAt': 'completed_at',
            }
            set_clauses: List[str] = []
            values: List[Any] = []
            for key, value in updates.items():
                db_key = field_mapping.get(key, key)
                set_clauses.append(f"{db_key} = ?")
                if key == 'tags':
                    values.append(json.dumps(value, ensure_ascii=False))
                else:
                    values.append(value)
            set_clauses.append("updated_at = ?")
            values.append(int(datetime.now().timestamp()))
            values.append(task_id)
            values.append(space_id)
            query = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?"
            cur = await conn.execute(query, values)
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update task error: {e}")
        return False


async def delete_task(task_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某空间任务"""
    try:
        async with get_db() as conn:
            cur = await conn.execute('DELETE FROM tasks WHERE id = ? AND space_id = ?', (task_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete task error: {e}")
        return False


async def get_tasks_by_project(project_id: str, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取指定项目在某空间下的所有任务"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            '''SELECT * FROM tasks WHERE project_id = ? AND space_id = ?
               ORDER BY priority DESC, created_at DESC''',
            (project_id, space_id),
        )
        return [task_to_dict(row) for row in rows]


__all__ = [
    "task_to_dict",
    "get_all_tasks",
    "get_task_by_id",
    "insert_task",
    "update_task",
    "delete_task",
    "get_tasks_by_project",
]
