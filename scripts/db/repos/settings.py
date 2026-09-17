"""Settings persistence repository."""
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

async def get_global_config(key: str) -> Optional[str]:
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT value FROM global_config WHERE key = ?', (key,))
        return row["value"] if row else None


async def get_all_global_configs() -> Dict[str, str]:
    async with get_db() as conn:
        rows = await _fetchall(conn, 'SELECT key, value FROM global_config')
        return {r["key"]: r["value"] for r in rows}


async def set_global_config(key: str, value: str) -> bool:
    async with get_db() as conn:
        now = int(time.time() * 1000)
        await conn.execute(
            'INSERT INTO global_config (key, value, updated_at) VALUES (?, ?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at',
            (key, value, now),
        )
        return True


async def set_global_configs(mapping: Dict[str, str]) -> None:
    if not mapping:
        return
    async with get_db() as conn:
        now = int(time.time() * 1000)
        for k, v in mapping.items():
            await conn.execute(
                'INSERT INTO global_config (key, value, updated_at) VALUES (?, ?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at',
                (k, v, now),
            )


__all__ = [
    "get_global_config",
    "get_all_global_configs",
    "set_global_config",
    "set_global_configs",
]
