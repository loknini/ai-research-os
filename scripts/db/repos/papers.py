"""Papers persistence repository."""
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

def paper_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将论文数据库行转换为字典"""
    return {
        'id': row['id'],
        'title': row['title'],
        'authors': json.loads(row['authors']),
        'abstract': row['abstract'],
        'arxivId': row['arxiv_id'],
        'pdfUrl': row['pdf_url'],
        'categories': json.loads(row['categories']) if row['categories'] else [],
        'publishedDate': row['published_date'],
        'localPath': row['local_path'],
        'summary': row['summary'],
        'bibtex': row['bibtex'] if 'bibtex' in row.keys() else None,
        'tags': json.loads(row['tags']) if row['tags'] else [],
        'isRead': bool(row['is_read']),
        'isFavorite': bool(row['is_favorite']),
        'addedAt': row['added_at'],
        'updatedAt': row['updated_at'],
    }


async def get_all_papers(space_id: str = DEFAULT_SPACE, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
    """获取某空间下所有论文"""
    async with get_db() as conn:
        query = 'SELECT * FROM papers WHERE space_id = ? ORDER BY added_at DESC'
        params: List[Any] = [space_id]
        if limit is not None:
            query += ' LIMIT ? OFFSET ?'
            params.extend([limit, offset])
        rows = await _fetchall(conn, query, params)
        return [paper_to_dict(row) for row in rows]


async def get_paper_by_id(paper_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 ID 获取论文（按空间过滤）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM papers WHERE id = ? AND space_id = ?', (paper_id, space_id))
        return paper_to_dict(row) if row else None


async def get_paper_by_arxiv(arxiv_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 arXiv ID 获取论文（按空间过滤，用于写前去重）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM papers WHERE arxiv_id = ? AND space_id = ?', (arxiv_id, space_id))
        return paper_to_dict(row) if row else None


async def insert_paper(paper: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """向某空间插入新论文"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            arxiv_id = str(paper['arxivId'])
            paper_id = str(paper['id'])
            # arXiv 抓取器历史上把业务标识直接当主键。主键仍需全局唯一，
            # 因此仅对官方抓取形态生成稳定的、带空间维度的存储 ID。
            if paper_id == arxiv_id:
                paper_id = str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"ai-research-os://papers/{space_id}/{arxiv_id}",
                ))
            await conn.execute('''
                INSERT INTO papers
                (id, title, authors, abstract, arxiv_id, pdf_url, categories,
                 published_date, local_path, summary, tags, is_read, is_favorite,
                 added_at, updated_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                paper_id,
                paper['title'],
                json.dumps(paper.get('authors', []), ensure_ascii=False),
                paper['abstract'],
                arxiv_id,
                paper['pdfUrl'],
                json.dumps(paper.get('categories', []), ensure_ascii=False),
                paper['publishedDate'],
                paper.get('localPath'),
                paper.get('summary'),
                json.dumps(paper.get('tags', []), ensure_ascii=False),
                1 if paper.get('isRead') else 0,
                1 if paper.get('isFavorite') else 0,
                paper.get('addedAt', now),
                now,
                space_id,
            ))
            return True
    except sqlite3.IntegrityError:
        # (space_id, arxiv_id) 空间内唯一；重复插入返回 False。
        return False
    except Exception as e:
        print(f"Error inserting paper: {e}")
        return False


async def update_paper(paper_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新某空间论文（WHERE 带 space_id 校验，防误伤他人数据）"""
    try:
        async with get_db() as conn:
            field_mapping = {
                'title': 'title',
                'authors': 'authors',
                'abstract': 'abstract',
                'pdfUrl': 'pdf_url',
                'categories': 'categories',
                'publishedDate': 'published_date',
                'localPath': 'local_path',
                'summary': 'summary',
                'bibtex': 'bibtex',
                'tags': 'tags',
                'isRead': 'is_read',
                'isFavorite': 'is_favorite',
            }
            set_clauses = []
            params: List[Any] = []
            for key, value in updates.items():
                if key in field_mapping:
                    db_field = field_mapping[key]
                    if key in ['authors', 'categories', 'tags']:
                        value = json.dumps(value, ensure_ascii=False)
                    elif key in ['isRead', 'isFavorite']:
                        value = 1 if value else 0
                    set_clauses.append(f"{db_field} = ?")
                    params.append(value)
            if not set_clauses:
                return False
            set_clauses.append("updated_at = ?")
            params.append(int(datetime.now().timestamp()))
            params.append(paper_id)
            params.append(space_id)
            query = f"UPDATE papers SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?"
            cur = await conn.execute(query, params)
            return cur.rowcount > 0
    except Exception as e:
        print(f"Error updating paper: {e}")
        return False


async def delete_paper(paper_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某空间论文"""
    try:
        async with get_db() as conn:
            cur = await conn.execute('DELETE FROM papers WHERE id = ? AND space_id = ?', (paper_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Error deleting paper: {e}")
        return False


async def get_papers_count(space_id: Optional[str] = None) -> int:
    """获取论文总数（不传 space_id 时返回全局总数，兼容遗留 CLI）"""
    async with get_db() as conn:
        if space_id:
            cur = await conn.execute('SELECT COUNT(*) FROM papers WHERE space_id = ?', (space_id,))
        else:
            cur = await conn.execute('SELECT COUNT(*) FROM papers')
        return (await cur.fetchone())[0]


async def migrate_from_json(json_path: Path):
    """从 JSON 文件迁移数据到 SQLite（按默认空间归档）"""
    if not json_path.exists():
        print(f"JSON file not found: {json_path}")
        return
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        papers = data.get('papers', [])
        if not papers:
            print("No papers to migrate")
            return
        print(f"Migrating {len(papers)} papers from JSON to SQLite...")
        success_count = 0
        skip_count = 0
        for paper in papers:
            existing = await get_paper_by_arxiv(paper.get('arxivId', ''), DEFAULT_SPACE)
            if existing:
                skip_count += 1
                continue
            if await insert_paper(paper, DEFAULT_SPACE):
                success_count += 1
            else:
                skip_count += 1
        print(f"Migration complete: {success_count} inserted, {skip_count} skipped")
        backup_path = json_path.with_suffix('.json.backup')
        json_path.rename(backup_path)
        print(f"Original JSON backed up to: {backup_path}")
    except Exception as e:
        print(f"Migration error: {e}")


__all__ = [
    "paper_to_dict",
    "get_all_papers",
    "get_paper_by_id",
    "get_paper_by_arxiv",
    "insert_paper",
    "update_paper",
    "delete_paper",
    "get_papers_count",
    "migrate_from_json",
]
