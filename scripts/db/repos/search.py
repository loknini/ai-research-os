"""Search persistence repository."""
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

from .experiments import experiment_to_dict
from .notes import note_to_dict
from .papers import paper_to_dict
from .projects import project_to_dict
from .tasks import task_to_dict

async def global_search(query: str, space_id: str = DEFAULT_SPACE, limit: int = 20) -> Dict[str, List[Dict[str, Any]]]:
    """某空间内的跨 Hub 全局搜索"""
    results = {
        'papers': [], 'tasks': [], 'projects': [], 'notes': [], 'experiments': [],
    }
    query_lower = query.lower()
    like = f'%{query_lower}%'
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            '''SELECT * FROM papers WHERE space_id = ? AND (LOWER(title) LIKE ? OR LOWER(abstract) LIKE ?)
               ORDER BY added_at DESC LIMIT ?''',
            (space_id, like, like, limit))
        results['papers'] = [paper_to_dict(r) for r in rows]

        rows = await _fetchall(
            conn,
            '''SELECT * FROM tasks WHERE space_id = ? AND (LOWER(title) LIKE ? OR LOWER(description) LIKE ?)
               ORDER BY created_at DESC LIMIT ?''',
            (space_id, like, like, limit))
        results['tasks'] = [task_to_dict(r) for r in rows]

        rows = await _fetchall(
            conn,
            '''SELECT * FROM software_projects WHERE space_id = ? AND (LOWER(name) LIKE ? OR LOWER(description) LIKE ?)
               ORDER BY created_at DESC LIMIT ?''',
            (space_id, like, like, limit))
        results['projects'] = [project_to_dict(r) for r in rows]

        rows = await _fetchall(
            conn,
            '''SELECT * FROM notes WHERE space_id = ? AND (LOWER(title) LIKE ? OR LOWER(content) LIKE ?)
               ORDER BY created_at DESC LIMIT ?''',
            (space_id, like, like, limit))
        results['notes'] = [note_to_dict(r) for r in rows]

        rows = await _fetchall(
            conn,
            '''SELECT * FROM experiments WHERE space_id = ? AND (LOWER(name) LIKE ? OR LOWER(description) LIKE ?)
               ORDER BY created_at DESC LIMIT ?''',
            (space_id, like, like, limit))
        results['experiments'] = [experiment_to_dict(r) for r in rows]

    return results


__all__ = [
    "global_search",
]
