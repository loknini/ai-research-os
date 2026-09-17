"""Experiments persistence repository."""
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

def experiment_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将实验数据库行转换为字典"""
    return {
        'id': row['id'],
        'name': row['name'],
        'description': row['description'],
        'projectId': row['project_id'],
        'status': row['status'],
        'config': json.loads(row['config']) if row['config'] else {},
        'tags': json.loads(row['tags']) if row['tags'] else [],
        'swanlabProject': row['swanlab_project'],
        'swanlabExperimentId': row['swanlab_experiment_id'],
        'totalRuns': row['total_runs'],
        'bestMetricName': row['best_metric_name'],
        'bestMetricValue': row['best_metric_value'],
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }


def run_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将实验运行记录数据库行转换为字典"""
    return {
        'id': row['id'],
        'experimentId': row['experiment_id'],
        'runNumber': row['run_number'],
        'status': row['status'],
        'config': json.loads(row['config']) if row['config'] else {},
        'metrics': json.loads(row['metrics']) if row['metrics'] else {},
        'swanlabRunId': row['swanlab_run_id'],
        'startedAt': row['started_at'],
        'endedAt': row['ended_at'],
        'duration': row['duration'],
    }


async def get_all_experiments(space_id: str = DEFAULT_SPACE, status: Optional[str] = None,
                              project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取某空间实验"""
    async with get_db() as conn:
        query = 'SELECT * FROM experiments WHERE space_id = ?'
        params: List[Any] = [space_id]
        if status:
            query += ' AND status = ?'
            params.append(status)
        if project_id:
            query += ' AND project_id = ?'
            params.append(project_id)
        query += ' ORDER BY updated_at DESC'
        rows = await _fetchall(conn, query, params)
        return [experiment_to_dict(row) for row in rows]


async def get_experiment_by_id(experiment_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 ID 获取实验（按空间过滤）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM experiments WHERE id = ? AND space_id = ?', (experiment_id, space_id))
        return experiment_to_dict(row) if row else None


async def get_experiment_runs(experiment_id: str, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间实验的所有运行记录（反范式按空间过滤）"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            'SELECT * FROM experiment_runs WHERE experiment_id = ? AND space_id = ? ORDER BY run_number DESC',
            (experiment_id, space_id))
        return [run_to_dict(row) for row in rows]


async def insert_experiment(experiment: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """向某空间插入新实验"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT INTO experiments
                (id, name, description, project_id, status, config, tags, swanlab_project,
                 swanlab_experiment_id, total_runs, created_at, updated_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                experiment['id'],
                experiment['name'],
                experiment.get('description', ''),
                experiment.get('projectId'),
                experiment.get('status', 'planning'),
                json.dumps(experiment.get('config', {}), ensure_ascii=False),
                json.dumps(experiment.get('tags', []), ensure_ascii=False),
                experiment.get('swanlabProject'),
                experiment.get('swanlabExperimentId'),
                experiment.get('totalRuns', 0),
                experiment.get('createdAt', now),
                now,
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Insert experiment error: {e}")
        return False


async def update_experiment(experiment_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新某空间实验"""
    try:
        async with get_db() as conn:
            allowed_fields = {
                'name', 'description', 'projectId', 'status', 'config', 'tags',
                'swanlabProject', 'swanlabExperimentId', 'totalRuns', 'bestMetricName', 'bestMetricValue',
            }
            updates = {k: v for k, v in updates.items() if k in allowed_fields}
            if not updates:
                return False
            field_mapping = {
                'projectId': 'project_id',
                'swanlabProject': 'swanlab_project',
                'swanlabExperimentId': 'swanlab_experiment_id',
                'totalRuns': 'total_runs',
                'bestMetricName': 'best_metric_name',
                'bestMetricValue': 'best_metric_value',
            }
            set_clauses: List[str] = []
            values: List[Any] = []
            for key, value in updates.items():
                db_key = field_mapping.get(key, key)
                set_clauses.append(f"{db_key} = ?")
                if key in ['config', 'tags']:
                    values.append(json.dumps(value, ensure_ascii=False))
                else:
                    values.append(value)
            set_clauses.append("updated_at = ?")
            values.append(int(datetime.now().timestamp()))
            values.append(experiment_id)
            values.append(space_id)
            query = f"UPDATE experiments SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?"
            cur = await conn.execute(query, values)
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update experiment error: {e}")
        return False


async def delete_experiment(experiment_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某空间实验"""
    try:
        async with get_db() as conn:
            cur = await conn.execute('DELETE FROM experiments WHERE id = ? AND space_id = ?', (experiment_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete experiment error: {e}")
        return False


async def insert_experiment_run(run: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """插入实验运行记录（反范式写入父空间）"""
    try:
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO experiment_runs
                (id, experiment_id, run_number, status, config, metrics, swanlab_run_id, started_at, ended_at, duration, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                run['id'],
                run['experimentId'],
                run['runNumber'],
                run.get('status', 'running'),
                json.dumps(run.get('config', {}), ensure_ascii=False),
                json.dumps(run.get('metrics', {}), ensure_ascii=False),
                run.get('swanlabRunId'),
                run['startedAt'],
                run.get('endedAt'),
                run.get('duration'),
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Insert experiment run error: {e}")
        return False


async def update_experiment_run(run_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新实验运行记录"""
    try:
        async with get_db() as conn:
            allowed_fields = {'status', 'metrics', 'endedAt', 'duration'}
            updates = {k: v for k, v in updates.items() if k in allowed_fields}
            if not updates:
                return False
            field_mapping = {'endedAt': 'ended_at'}
            set_clauses: List[str] = []
            values: List[Any] = []
            for key, value in updates.items():
                db_key = field_mapping.get(key, key)
                set_clauses.append(f"{db_key} = ?")
                if key == 'metrics':
                    values.append(json.dumps(value, ensure_ascii=False))
                else:
                    values.append(value)
            values.append(run_id)
            values.append(space_id)
            query = f"UPDATE experiment_runs SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?"
            cur = await conn.execute(query, values)
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update experiment run error: {e}")
        return False


__all__ = [
    "experiment_to_dict",
    "run_to_dict",
    "get_all_experiments",
    "get_experiment_by_id",
    "get_experiment_runs",
    "insert_experiment",
    "update_experiment",
    "delete_experiment",
    "insert_experiment_run",
    "update_experiment_run",
]
