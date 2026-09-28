"""Persist RAG generation identity and resumable phase checkpoints."""
from __future__ import annotations

import aiosqlite

from .runner import migration_file_checksum

VERSION = 2
NAME = "rag_resumable_generations"
CHECKSUM = "pending"


async def _columns(conn: aiosqlite.Connection, table: str) -> set[str]:
    rows = await (await conn.execute(f"PRAGMA table_info({table})")).fetchall()
    return {str(row["name"]) for row in rows}


async def upgrade(conn: aiosqlite.Connection | None) -> None:
    if conn is None:
        raise RuntimeError("v2 requires a transactional connection")
    columns = await _columns(conn, "rag_index_jobs")
    additions = (
        ("generation_id", "TEXT"),
        ("phase", "TEXT NOT NULL DEFAULT 'queued'"),
        ("checkpoint", "TEXT NOT NULL DEFAULT '{}'"),
    )
    for name, ddl in additions:
        if name not in columns:
            await conn.execute(f"ALTER TABLE rag_index_jobs ADD COLUMN {name} {ddl}")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rag_jobs_generation "
        "ON rag_index_jobs(space_id, source_id, generation_id)"
    )


async def validate(conn: aiosqlite.Connection) -> None:
    columns = await _columns(conn, "rag_index_jobs")
    required = {"generation_id", "phase", "checkpoint"}
    missing = required - columns
    if missing:
        raise RuntimeError(f"rag_index_jobs missing resumability columns: {sorted(missing)}")


# Applied migration files are immutable. The checksum excludes this assignment line.
CHECKSUM = migration_file_checksum(__file__)


__all__ = ["VERSION", "NAME", "CHECKSUM", "upgrade", "validate"]
