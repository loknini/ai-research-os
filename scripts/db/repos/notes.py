"""Notes persistence repository."""
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

def note_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将笔记数据库行转换为字典"""
    return {
        'id': row['id'],
        'title': row['title'],
        'content': row['content'],
        'summary': row['summary'],
        'type': row['type'],
        'tags': json.loads(row['tags']) if row['tags'] else [],
        'paperId': row['paper_id'],
        'projectId': row['project_id'],
        'parentNoteId': row['parent_note_id'],
        'isFavorite': bool(row['is_favorite']),
        'aiGenerated': bool(row['ai_generated']),
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }


async def get_all_notes(space_id: str = DEFAULT_SPACE, note_type: Optional[str] = None,
                        paper_id: Optional[str] = None, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取某空间笔记，支持按类型、论文、项目筛选"""
    async with get_db() as conn:
        query = 'SELECT * FROM notes WHERE space_id = ?'
        params: List[Any] = [space_id]
        if note_type:
            query += ' AND type = ?'
            params.append(note_type)
        if paper_id:
            query += ' AND paper_id = ?'
            params.append(paper_id)
        if project_id:
            query += ' AND project_id = ?'
            params.append(project_id)
        query += ' ORDER BY updated_at DESC'
        rows = await _fetchall(conn, query, params)
        return [note_to_dict(row) for row in rows]


async def get_note_by_id(note_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 ID 获取笔记（按空间过滤）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM notes WHERE id = ? AND space_id = ?', (note_id, space_id))
        return note_to_dict(row) if row else None


async def get_note_links(note_id: str, space_id: str = DEFAULT_SPACE) -> List[str]:
    """获取笔记的链接目标 ID 列表（按空间过滤）"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT target_note_id FROM note_links WHERE source_note_id = ? AND space_id = ?',
            (note_id, space_id))
        return [row['target_note_id'] for row in rows]


async def get_linked_notes(note_id: str, space_id: str = DEFAULT_SPACE) -> List[str]:
    """获取链接到该笔记的源笔记 ID 列表（按空间过滤）"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT source_note_id FROM note_links WHERE target_note_id = ? AND space_id = ?',
            (note_id, space_id))
        return [row['source_note_id'] for row in rows]


async def insert_note(note: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """向某空间插入新笔记"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT INTO notes
                (id, title, content, summary, type, tags, paper_id, project_id, parent_note_id,
                 is_favorite, ai_generated, created_at, updated_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                note['id'],
                note['title'],
                note.get('content', ''),
                note.get('summary'),
                note.get('type', 'note'),
                json.dumps(note.get('tags', []), ensure_ascii=False),
                note.get('paperId'),
                note.get('projectId'),
                note.get('parentNoteId'),
                1 if note.get('isFavorite') else 0,
                1 if note.get('aiGenerated') else 0,
                note.get('createdAt', now),
                now,
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Insert note error: {e}")
        return False


async def update_note(note_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新某空间笔记（先按空间取当前值生成版本，再按空间更新）"""
    try:
        async with get_db() as conn:
            allowed_fields = {
                'title', 'content', 'summary', 'type', 'tags',
                'paperId', 'projectId', 'parentNoteId', 'isFavorite', 'aiGenerated',
            }
            updates = {k: v for k, v in updates.items() if k in allowed_fields}
            if not updates:
                return False
            current_note = await get_note_by_id(note_id, space_id)
            if current_note:
                change_summary = f"更新: {', '.join(updates.keys())}"
                await create_version('note', note_id, current_note, change_summary, space_id=space_id)
            field_mapping = {
                'paperId': 'paper_id',
                'projectId': 'project_id',
                'parentNoteId': 'parent_note_id',
                'isFavorite': 'is_favorite',
                'aiGenerated': 'ai_generated',
            }
            set_clauses: List[str] = []
            values: List[Any] = []
            for key, value in updates.items():
                db_key = field_mapping.get(key, key)
                set_clauses.append(f"{db_key} = ?")
                if key == 'tags':
                    values.append(json.dumps(value, ensure_ascii=False))
                elif key in ['isFavorite', 'aiGenerated']:
                    values.append(1 if value else 0)
                else:
                    values.append(value)
            set_clauses.append("updated_at = ?")
            values.append(int(datetime.now().timestamp()))
            values.append(note_id)
            values.append(space_id)
            query = f"UPDATE notes SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?"
            cur = await conn.execute(query, values)
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update note error: {e}")
        return False


async def delete_note(note_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某空间笔记（级联删除 note_links，且严格限定本空间）"""
    try:
        async with get_db() as conn:
            cur = await conn.execute('DELETE FROM notes WHERE id = ? AND space_id = ?', (note_id, space_id))
            await conn.execute(
                'DELETE FROM note_links WHERE (source_note_id = ? OR target_note_id = ?) AND space_id = ?',
                (note_id, note_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete note error: {e}")
        return False


async def add_note_link(source_note_id: str, target_note_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """添加笔记链接（反范式写入父空间，便于按空间过滤）"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT OR IGNORE INTO note_links (source_note_id, target_note_id, created_at, space_id)
                VALUES (?, ?, ?, ?)
            ''', (source_note_id, target_note_id, now, space_id))
            return True
    except Exception as e:
        print(f"Add note link error: {e}")
        return False


__all__ = [
    "note_to_dict",
    "get_all_notes",
    "get_note_by_id",
    "get_note_links",
    "get_linked_notes",
    "insert_note",
    "update_note",
    "delete_note",
    "add_note_link",
]
