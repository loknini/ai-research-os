"""Shared SQLite connection, retry and runtime path primitives."""
from __future__ import annotations

import asyncio
import os
import random
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import aiosqlite

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data"))
DB_PATH = Path(os.environ.get("DB_PATH", DATA_DIR / "ai_research_os.db"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SPACE = "__default__"

# Tables whose legacy forms may need the common space_id compatibility step.
SPACE_TABLES = [
    "papers", "cron_jobs", "software_projects", "tasks", "code_generations",
    "notes", "note_links", "experiments", "experiment_runs", "version_history",
    "conversations", "chat_messages", "agent_sessions", "agent_messages",
    "agent_generated_files", "formula_history", "obsidian_vaults", "obsidian_files",
    "agent_runs", "agent_run_events", "agent_tool_approvals", "agent_replay_messages",
    "agent_teams", "agent_role_templates", "agent_run_nodes",
    "rag_sources", "rag_documents", "rag_chunks", "rag_index_jobs",
    "development_run_steps", "development_artifacts",
]


def configure_paths(
    *,
    data_dir: str | Path | None = None,
    db_path: str | Path | None = None,
) -> tuple[Path, Path]:
    """Override storage paths for isolated tools/tests before database work."""
    global DATA_DIR, DB_PATH
    if data_dir is not None:
        DATA_DIR = Path(data_dir)
    if db_path is not None:
        DB_PATH = Path(db_path)
        if data_dir is None:
            DATA_DIR = DB_PATH.parent
    elif data_dir is not None:
        DB_PATH = DATA_DIR / "ai_research_os.db"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR, DB_PATH


def _clean_text_for_db(text: Optional[str]) -> Optional[str]:
    """Remove surrogate code points that SQLite's UTF-8 encoder rejects."""
    if text is None:
        return None
    return text.encode("utf-8", errors="ignore").decode("utf-8")


@asynccontextmanager
async def get_db(busy_timeout_ms: int = 5000):
    """Open one independently managed WAL-mode connection per operation."""
    conn = None
    last_err: Optional[Exception] = None
    for attempt in range(5):
        try:
            conn = await aiosqlite.connect(str(DB_PATH))
            conn.row_factory = aiosqlite.Row
            await conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            break
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if conn is not None:
                await conn.close()
                conn = None
            last_err = exc
            if "database is locked" in message or "busy" in message:
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            raise
    else:
        assert last_err is not None
        raise last_err

    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
        await conn.close()


async def _fetchall(
    conn: aiosqlite.Connection,
    query: str,
    params: tuple = (),
) -> list[aiosqlite.Row]:
    cursor = await conn.execute(query, params)
    return await cursor.fetchall()


async def _fetchone(
    conn: aiosqlite.Connection,
    query: str,
    params: tuple = (),
) -> aiosqlite.Row | None:
    cursor = await conn.execute(query, params)
    return await cursor.fetchone()


def _is_locked_error(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.OperationalError):
        message = str(exc).lower()
        return "database is locked" in message or "busy" in message
    return False


async def with_busy_retry(
    fn: Callable[[], Awaitable[Any]],
    attempts: int = 5,
    what: str = "db-op",
):
    """Retry a complete idempotent database operation on SQLite lock errors."""
    last_err: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return await fn()
        except Exception as exc:
            if not _is_locked_error(exc):
                raise
            last_err = exc
            delay = 0.3 * (2 ** attempt) + random.uniform(0, 0.3 * (attempt + 1))
            print(f"[db] {what} locked (attempt {attempt + 1}/{attempts}), retry in {delay:.1f}s")
            await asyncio.sleep(delay)
    assert last_err is not None
    raise last_err


__all__ = [
    "DATA_DIR",
    "DB_PATH",
    "DEFAULT_SPACE",
    "PROJECT_ROOT",
    "SPACE_TABLES",
    "_clean_text_for_db",
    "_fetchall",
    "_fetchone",
    "_is_locked_error",
    "configure_paths",
    "get_db",
    "with_busy_retry",
]
