"""Versions persistence repository."""
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

async def create_version(entity_type: str, entity_id: str, data: Dict[str, Any],
                         change_summary: str = '', created_by: str = 'user',
                         space_id: str = DEFAULT_SPACE) -> bool:
    """创建新版本记录（按空间生成版本号）"""
    try:
        async with get_db() as conn:
            row = await _fetchone(
                conn,
                'SELECT MAX(version_number) as max_version FROM version_history WHERE entity_id = ? AND space_id = ?',
                (entity_id, space_id))
            next_version = (row['max_version'] or 0) + 1
            version_id = str(uuid.uuid4())
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT INTO version_history
                (id, entity_type, entity_id, version_number, data, change_summary, created_by, created_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                version_id,
                entity_type,
                entity_id,
                next_version,
                json.dumps(data, ensure_ascii=False),
                change_summary,
                created_by,
                now,
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Create version error: {e}")
        return False


async def get_versions(entity_type: str, entity_id: str, limit: int = 50,
                       space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间实体的版本历史"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            '''SELECT * FROM version_history
               WHERE entity_type = ? AND entity_id = ? AND space_id = ?
               ORDER BY version_number DESC LIMIT ?''',
            (entity_type, entity_id, space_id, limit))
        return [_version_row_to_dict(row) for row in rows]


async def get_version_by_id(version_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据ID获取特定版本（按空间过滤）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM version_history WHERE id = ? AND space_id = ?', (version_id, space_id))
        return _version_row_to_dict(row) if row else None


def _version_row_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    return {
        'id': row['id'],
        'entityType': row['entity_type'],
        'entityId': row['entity_id'],
        'versionNumber': row['version_number'],
        'data': json.loads(row['data']),
        'changeSummary': row['change_summary'],
        'createdBy': row['created_by'],
        'createdAt': row['created_at'],
    }


async def compare_versions(version_id1: str, version_id2: str, space_id: str = DEFAULT_SPACE) -> Dict[str, Any]:
    """对比两个版本的差异（按空间过滤）"""
    v1 = await get_version_by_id(version_id1, space_id)
    v2 = await get_version_by_id(version_id2, space_id)
    if not v1 or not v2:
        return {'error': 'Version not found'}
    diff = {'added': {}, 'removed': {}, 'modified': {}}
    data1 = v1['data']
    data2 = v2['data']
    all_keys = set(data1.keys()) | set(data2.keys())
    for key in all_keys:
        if key not in data1:
            diff['added'][key] = data2[key]
        elif key not in data2:
            diff['removed'][key] = data1[key]
        elif data1[key] != data2[key]:
            diff['modified'][key] = {'old': data1[key], 'new': data2[key]}
    return {'version1': v1, 'version2': v2, 'diff': diff}


async def restore_version(version_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """恢复到指定版本（在本空间内新建版本）"""
    version = await get_version_by_id(version_id, space_id)
    if not version:
        return None
    await create_version(
        entity_type=version['entityType'],
        entity_id=version['entityId'],
        data=version['data'],
        change_summary=f"恢复到版本 #{version['versionNumber']}",
        created_by='system',
        space_id=space_id,
    )
    return version['data']


async def delete_old_versions(entity_type: str, entity_id: str, keep_count: int = 20,
                              space_id: str = DEFAULT_SPACE) -> int:
    """删除旧版本，只保留最近的N个（按空间过滤）"""
    try:
        async with get_db() as conn:
            rows = await _fetchall(
                conn,
                '''SELECT id FROM version_history
                   WHERE entity_type = ? AND entity_id = ? AND space_id = ?
                   ORDER BY version_number DESC LIMIT -1 OFFSET ?''',
                (entity_type, entity_id, space_id, keep_count))
            ids_to_delete = [row['id'] for row in rows]
            if ids_to_delete:
                placeholders = ','.join(['?'] * len(ids_to_delete))
                await conn.execute(f"DELETE FROM version_history WHERE id IN ({placeholders})", ids_to_delete)
            return len(ids_to_delete)
    except Exception as e:
        print(f"Delete old versions error: {e}")
        return 0


__all__ = [
    "create_version",
    "get_versions",
    "get_version_by_id",
    "_version_row_to_dict",
    "compare_versions",
    "restore_version",
    "delete_old_versions",
]
