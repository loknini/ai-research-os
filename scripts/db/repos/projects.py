"""Projects persistence repository."""
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

def project_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将项目数据库行转换为字典"""
    return {
        'id': row['id'],
        'name': row['name'],
        'description': row['description'],
        'ideaDescription': row['idea_description'],
        'techStack': json.loads(row['tech_stack']) if row['tech_stack'] else [],
        'status': row['status'],
        'localPath': row['local_path'],
        'githubUrl': row['github_url'],
        'architecture': json.loads(row['architecture']) if row['architecture'] else {},
        'features': json.loads(row['features']) if row['features'] else [],
        'milestones': json.loads(row['milestones']) if row['milestones'] else [],
        'aiGeneratedCode': bool(row['ai_generated_code']),
        'developmentConfig': (json.loads(row['development_config'])
                              if 'development_config' in row.keys() and row['development_config'] else {}),
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }


async def get_all_projects(space_id: str = DEFAULT_SPACE, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取某空间项目，支持按状态筛选"""
    async with get_db() as conn:
        query = 'SELECT * FROM software_projects WHERE space_id = ?'
        params: List[Any] = [space_id]
        if status:
            query += ' AND status = ?'
            params.append(status)
        query += ' ORDER BY updated_at DESC'
        rows = await _fetchall(conn, query, params)
        return [project_to_dict(row) for row in rows]


async def get_project_by_id(project_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 ID 获取项目（按空间过滤）"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM software_projects WHERE id = ? AND space_id = ?', (project_id, space_id))
        return project_to_dict(row) if row else None


async def insert_project(project: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """向某空间插入新项目"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT INTO software_projects
                (id, name, description, idea_description, tech_stack, status, local_path,
                 github_url, architecture, features, milestones, ai_generated_code, created_at, updated_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                project['id'],
                project['name'],
                project.get('description', ''),
                project.get('ideaDescription', ''),
                json.dumps(project.get('techStack', []), ensure_ascii=False),
                project.get('status', 'design'),
                project.get('localPath'),
                project.get('githubUrl'),
                json.dumps(project.get('architecture', {}), ensure_ascii=False),
                json.dumps(project.get('features', []), ensure_ascii=False),
                json.dumps(project.get('milestones', []), ensure_ascii=False),
                1 if project.get('aiGeneratedCode') else 0,
                project.get('createdAt', now),
                now,
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Insert project error: {e}")
        return False


async def update_project(project_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新某空间项目"""
    try:
        async with get_db() as conn:
            allowed_fields = {
                'name', 'description', 'ideaDescription', 'techStack', 'status',
                'localPath', 'githubUrl', 'architecture', 'features', 'milestones', 'aiGeneratedCode',
                'developmentConfig',
            }
            updates = {k: v for k, v in updates.items() if k in allowed_fields}
            if not updates:
                return False
            field_mapping = {
                'ideaDescription': 'idea_description',
                'techStack': 'tech_stack',
                'localPath': 'local_path',
                'githubUrl': 'github_url',
                'aiGeneratedCode': 'ai_generated_code',
                'developmentConfig': 'development_config',
            }
            set_clauses: List[str] = []
            values: List[Any] = []
            for key, value in updates.items():
                db_key = field_mapping.get(key, key)
                set_clauses.append(f"{db_key} = ?")
                if key in ['techStack', 'architecture', 'features', 'milestones', 'developmentConfig']:
                    values.append(json.dumps(value, ensure_ascii=False))
                elif key == 'aiGeneratedCode':
                    values.append(1 if value else 0)
                else:
                    values.append(value)
            set_clauses.append("updated_at = ?")
            values.append(int(datetime.now().timestamp()))
            values.append(project_id)
            values.append(space_id)
            query = f"UPDATE software_projects SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?"
            cur = await conn.execute(query, values)
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update project error: {e}")
        return False


async def delete_project(project_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某空间项目（级联删除关联任务和代码生成记录）"""
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                'DELETE FROM software_projects WHERE id = ? AND space_id = ?', (project_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete project error: {e}")
        return False


def code_gen_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将代码生成记录数据库行转换为字典"""
    return {
        'id': row['id'],
        'projectId': row['project_id'],
        'prompt': row['prompt'],
        'generatedCode': row['generated_code'],
        'filePath': row['file_path'],
        'language': row['language'],
        'status': row['status'],
        'createdAt': row['created_at'],
    }


async def get_code_generations_by_project(project_id: str, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间项目下的代码生成历史"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            '''SELECT * FROM code_generations WHERE project_id = ? AND space_id = ?
               ORDER BY created_at DESC''',
            (project_id, space_id),
        )
        return [code_gen_to_dict(row) for row in rows]


async def insert_code_generation(code_gen: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """向某空间插入代码生成记录（反范式写入父空间）"""
    try:
        async with get_db() as conn:
            now = int(datetime.now().timestamp())
            await conn.execute('''
                INSERT INTO code_generations
                (id, project_id, prompt, generated_code, file_path, language, status, created_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                code_gen['id'],
                code_gen['projectId'],
                code_gen['prompt'],
                code_gen['generatedCode'],
                code_gen.get('filePath'),
                code_gen.get('language'),
                code_gen.get('status', 'pending'),
                code_gen.get('createdAt', now),
                space_id,
            ))
            return True
    except Exception as e:
        print(f"Insert code generation error: {e}")
        return False


async def update_code_generation_status(code_gen_id: str, status: str, space_id: str = DEFAULT_SPACE) -> bool:
    """更新代码生成记录状态"""
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                'UPDATE code_generations SET status = ? WHERE id = ? AND space_id = ?',
                (status, code_gen_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update code generation status error: {e}")
        return False


__all__ = [
    "project_to_dict",
    "get_all_projects",
    "get_project_by_id",
    "insert_project",
    "update_project",
    "delete_project",
    "code_gen_to_dict",
    "get_code_generations_by_project",
    "insert_code_generation",
    "update_code_generation_status",
]
