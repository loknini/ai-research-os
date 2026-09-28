"""Add local-file fingerprints, chunk hashes, and a persistent embedding cache."""
from __future__ import annotations

import aiosqlite

from .runner import migration_file_checksum

VERSION = 3
NAME = "rag_incremental_cache"
CHECKSUM = "pending"


async def _columns(conn: aiosqlite.Connection, table: str) -> set[str]:
    rows = await (await conn.execute(f"PRAGMA table_info({table})")).fetchall()
    return {str(row["name"]) for row in rows}


async def upgrade(conn: aiosqlite.Connection | None) -> None:
    if conn is None:
        raise RuntimeError("v3 requires a transactional connection")

    doc_columns = await _columns(conn, "rag_documents")
    for name, ddl in (
        ("file_mtime_ns", "INTEGER"),
        ("index_signature", "TEXT"),
    ):
        if name not in doc_columns:
            await conn.execute(f"ALTER TABLE rag_documents ADD COLUMN {name} {ddl}")

    chunk_columns = await _columns(conn, "rag_chunks")
    if "chunk_hash" not in chunk_columns:
        await conn.execute("ALTER TABLE rag_chunks ADD COLUMN chunk_hash TEXT")

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_embedding_cache (
            space_id TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            chunk_hash TEXT NOT NULL,
            embedding TEXT NOT NULL,
            dims INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            last_used_at INTEGER NOT NULL,
            PRIMARY KEY (space_id, profile_id, chunk_hash)
        )
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rag_docs_fingerprint "
        "ON rag_documents(space_id, source_id, file_path, generation_id)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rag_chunks_hash "
        "ON rag_chunks(space_id, chunk_hash)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rag_embedding_cache_used "
        "ON rag_embedding_cache(space_id, last_used_at)"
    )


async def validate(conn: aiosqlite.Connection) -> None:
    doc_columns = await _columns(conn, "rag_documents")
    chunk_columns = await _columns(conn, "rag_chunks")
    if not {"file_mtime_ns", "index_signature"}.issubset(doc_columns):
        raise RuntimeError("rag_documents missing incremental fingerprint columns")
    if "chunk_hash" not in chunk_columns:
        raise RuntimeError("rag_chunks missing chunk_hash")
    tables = await (await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rag_embedding_cache'"
    )).fetchall()
    if not tables:
        raise RuntimeError("rag_embedding_cache table is missing")


CHECKSUM = migration_file_checksum(__file__)


__all__ = ["VERSION", "NAME", "CHECKSUM", "upgrade", "validate"]
