"""Formula persistence repository."""
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

async def update_formula_history_record(
    record_id: str,
    updates: Dict[str, Any],
    space_id: str = DEFAULT_SPACE,
) -> bool:
    """按空间更新公式记录；返回 False 表示记录不存在或没有有效字段。"""
    field_mapping = {
        "latex_code": "latex_code",
        "latexCode": "latex_code",
        "is_favorite": "is_favorite",
        "isFavorite": "is_favorite",
        "tags": "tags",
        "note": "note",
    }
    normalized = {
        column: value
        for key, value in updates.items()
        if (column := field_mapping.get(key)) is not None
    }
    if not normalized:
        return False

    async def _update() -> bool:
        async with get_db(busy_timeout_ms=30000) as conn:
            clauses: List[str] = []
            values: List[Any] = []
            for column, value in normalized.items():
                if column == "tags":
                    value = json.dumps(value, ensure_ascii=False)
                elif column == "is_favorite":
                    value = 1 if value else 0
                clauses.append(f"{column} = ?")
                values.append(value)
            values.extend([record_id, space_id])
            cur = await conn.execute(
                f"UPDATE formula_history SET {', '.join(clauses)} "
                "WHERE id = ? AND space_id = ?",
                values,
            )
            return cur.rowcount > 0

    return await with_busy_retry(_update, what="formula-update")


async def delete_formula_history_record(
    record_id: str,
    space_id: str = DEFAULT_SPACE,
) -> bool:
    """按空间删除公式记录；返回 False 表示记录不存在。"""
    async def _delete() -> bool:
        async with get_db(busy_timeout_ms=30000) as conn:
            cur = await conn.execute(
                "DELETE FROM formula_history WHERE id = ? AND space_id = ?",
                (record_id, space_id),
            )
            return cur.rowcount > 0

    return await with_busy_retry(_delete, what="formula-delete")


__all__ = [
    "update_formula_history_record",
    "delete_formula_history_record",
]
