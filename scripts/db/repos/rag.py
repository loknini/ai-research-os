"""Rag persistence repository."""
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

def _rag_source_to_dict(row) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    try:
        _kind = row["kind"]
    except Exception:
        _kind = "local"

    def _col(name: str, default=None):
        try:
            v = row[name]
            return default if v is None else v
        except Exception:
            return default

    return {
        "id": row["id"],
        "spaceId": row["space_id"],
        "name": row["name"],
        "kind": _kind or "local",
        "targetPaths": json.loads(row["target_paths"]) if row["target_paths"] else [],
        "recursive": bool(row["recursive"]),
        "fileTypes": json.loads(row["file_types"]) if row["file_types"] else [],
        "status": row["status"],
        "docCount": row["doc_count"],
        "chunkCount": row["chunk_count"],
        "progress": _col("progress", 0) or 0,
        "totalFiles": _col("total_files", 0) or 0,
        "embeddingModel": row["embedding_model"],
        "embeddingProvider": _col("embedding_provider"),
        "embeddingRevision": _col("embedding_revision"),
        "embeddingDims": _col("embedding_dims", 0) or 0,
        "embeddingProfileId": _col("embedding_profile_id"),
        "activeGenerationId": _col("active_generation_id"),
        "embedMode": row["embed_mode"],
        "error": row["error"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


async def create_rag_source(source_id: str, space_id: str, name: str, target_paths: Any,
                            recursive: bool, file_types: Any, embedding_model: str = "",
                            status: str = "pending", kind: str = "local") -> bool:
    """创建一条索引源记录（按空间打标）。target_paths / file_types 为列表。"""
    if kind not in ("local", "paper", "web"):
        kind = "local"
    try:
        now = int(time.time() * 1000)
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO rag_sources
                (id, space_id, name, kind, target_paths, recursive, file_types, status,
                 doc_count, chunk_count, embedding_model, embed_mode, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 'keyword', NULL, ?, ?)
            ''', (
                source_id, space_id, name, kind,
                json.dumps(target_paths, ensure_ascii=False),
                1 if recursive else 0,
                json.dumps(file_types, ensure_ascii=False),
                status, embedding_model, now, now,
            ))
        return True
    except Exception as e:
        print(f"Create rag source error: {e}")
        return False


async def update_rag_source(source_id: str, space_id: str, **fields: Any) -> bool:
    """白名单字段更新 rag_sources（按空间校验）。updated_at 自动刷新。"""
    allowed = {
        "name", "kind", "target_paths", "recursive", "file_types", "status",
        "doc_count", "chunk_count", "progress", "total_files",
        "embedding_model", "embedding_provider", "embedding_revision",
        "embedding_dims", "embedding_profile_id", "active_generation_id", "embed_mode",
        "error", "updated_at",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "updated_at" not in updates:
        updates["updated_at"] = int(time.time() * 1000)
    if not updates:
        return False
    set_clauses: List[str] = []
    values: List[Any] = []
    for key, value in updates.items():
        if key == "target_paths" and isinstance(value, (list, tuple)):
            value = json.dumps(list(value), ensure_ascii=False)
        elif key == "file_types" and isinstance(value, (list, tuple)):
            value = json.dumps(list(value), ensure_ascii=False)
        elif key == "recursive":
            value = 1 if value else 0
        set_clauses.append(f"{key} = ?")
        values.append(value)
    values.append(source_id)
    values.append(space_id)
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                f"UPDATE rag_sources SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?", values)
        return cur.rowcount > 0
    except Exception as e:
        print(f"Update rag source error: {e}")
        return False


async def upsert_rag_embedding_profile(profile: Dict[str, Any]) -> bool:
    """登记不可变嵌入配置。profile id 由调用方按配置内容生成。"""
    try:
        async with get_db() as conn:
            await conn.execute('''
                INSERT OR IGNORE INTO rag_embedding_profiles
                (id, provider, model, revision, dims, normalized, query_instruction, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                profile["id"], profile["provider"], profile["model"],
                profile.get("revision"), int(profile.get("dims") or 0),
                1 if profile.get("normalized", True) else 0,
                profile.get("query_instruction"), int(time.time() * 1000),
            ))
        return True
    except Exception as e:
        print(f"Create rag embedding profile error: {e}")
        return False


async def get_rag_embedding_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    if not profile_id:
        return None
    async with get_db() as conn:
        row = await _fetchone(
            conn, "SELECT * FROM rag_embedding_profiles WHERE id = ?", (profile_id,))
        return dict(row) if row else None


async def activate_rag_generation(source_id: str, space_id: str, generation_id: str,
                                  *, status: str, doc_count: int, chunk_count: int,
                                  embed_mode: str, profile: Optional[Dict[str, Any]] = None) -> bool:
    """单事务切换可见代次；切换前旧代始终可检索，切换后新代立即完整可见。"""
    profile = profile or {}
    try:
        async with get_db(busy_timeout_ms=30000) as conn:
            cur = await conn.execute('''
                UPDATE rag_sources SET active_generation_id = ?, status = ?, doc_count = ?,
                    chunk_count = ?, embed_mode = ?, embedding_model = ?,
                    embedding_provider = ?, embedding_revision = ?, embedding_dims = ?,
                    embedding_profile_id = ?, progress = 100, error = NULL, updated_at = ?
                WHERE id = ? AND space_id = ?
            ''', (
                generation_id, status, doc_count, chunk_count, embed_mode,
                profile.get("model"), profile.get("provider"), profile.get("revision"),
                int(profile.get("dims") or 0), profile.get("id"), int(time.time() * 1000),
                source_id, space_id,
            ))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Activate rag generation error: {e}")
        return False


async def clear_rag_generation(source_id: str, space_id: str, generation_id: str,
                               *, keep: bool = False, batch_size: int = 500) -> int:
    """删除某代，或在 keep=True 时删除该源除指定代外的历史数据。"""
    total = 0
    op = "<>" if keep else "="
    # NULL 表示 2.0 之前的旧代；激活新代后也应一并清掉。
    gen_clause = f"(generation_id {op} ? OR generation_id IS NULL)" if keep else "generation_id = ?"
    while True:
        async def _clear_batch() -> int:
            async with get_db(busy_timeout_ms=30000) as conn:
                rows = await _fetchall(
                    conn,
                    f"SELECT id FROM rag_chunks WHERE source_id = ? AND space_id = ? AND {gen_clause} LIMIT ?",
                    (source_id, space_id, generation_id, batch_size))
                ids = [r["id"] for r in rows]
                if not ids:
                    return 0
                await _vec_delete_for_conn(conn, space_id, ids)
                await _fts_delete_by_chunk_ids(conn, space_id, ids)
                placeholders = ",".join("?" for _ in ids)
                cur = await conn.execute(
                    f"DELETE FROM rag_chunks WHERE space_id = ? AND id IN ({placeholders})",
                    [space_id, *ids])
                return cur.rowcount or 0
        n = await with_busy_retry(_clear_batch, what=f"rag-generation-clear({source_id[:8]})")
        total += n
        if n <= 0:
            break
    async with get_db(busy_timeout_ms=30000) as conn:
        await conn.execute(
            f"DELETE FROM rag_documents WHERE source_id = ? AND space_id = ? AND {gen_clause}",
            (source_id, space_id, generation_id))
    return total


async def get_rag_source(source_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM rag_sources WHERE id = ? AND space_id = ?', (source_id, space_id))
        return _rag_source_to_dict(row) if row else None


async def get_rag_sources(space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        rows = await _fetchall(conn, 'SELECT * FROM rag_sources WHERE space_id = ? ORDER BY created_at DESC', (space_id,))
        return [_rag_source_to_dict(r) for r in rows]


async def delete_rag_source(source_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除索引源 + 其下全部文档与切片（级联）。

    切片经 ``clear_rag_chunks`` 分批独立小事务删除，大源单事务全量删持写锁
    过久，多 worker 下撞锁；整函数幂等，可安全重入。
    """
    try:
        await clear_rag_chunks(source_id, space_id)
        async with get_db(busy_timeout_ms=30000) as conn:
            await conn.execute('DELETE FROM rag_documents WHERE source_id = ? AND space_id = ?', (source_id, space_id))
            cur = await conn.execute('DELETE FROM rag_sources WHERE id = ? AND space_id = ?', (source_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete rag source error: {e}")
        return False


async def clear_rag_chunks(source_id: str, space_id: str = DEFAULT_SPACE,
                           batch_size: int = 500) -> int:
    """分批清空某源全部切片（每批独立小事务 + 锁重试），返回删除总数。

    单事务全量 DELETE 在万级切片下持写锁过久，多 worker 下必现 database is locked；
    逐批提交让其它写者插空，重试幂等。FTS 先按 id 集合删（一条语句一次扫描），
    再删主表（PK 索引，无逐行触发器）。
    """
    total = 0

    async def _clear_batch() -> int:
        async with get_db(busy_timeout_ms=30000) as conn:
            rows = await _fetchall(
                conn, 'SELECT id FROM rag_chunks WHERE source_id = ? AND space_id = ? LIMIT ?',
                (source_id, space_id, batch_size))
            ids = [r["id"] for r in rows]
            if not ids:
                return 0
            await _vec_delete_for_conn(conn, space_id, ids)
            await _fts_delete_by_chunk_ids(conn, space_id, ids)
            placeholders = ",".join("?" for _ in ids)
            cur = await conn.execute(
                f"DELETE FROM rag_chunks WHERE space_id = ? AND id IN ({placeholders})",
                [space_id, *ids])
            return cur.rowcount or 0

    while True:
        n = await with_busy_retry(
            _clear_batch, what=f"rag-clear({str(source_id)[:8]})")
        total += n
        if n <= 0:
            break
    return total


def _rag_document_to_dict(row) -> Optional[Dict[str, Any]]:
    if not row:
        return None

    def _col(name: str, default=None):
        try:
            return row[name]
        except Exception:
            return default

    return {
        "id": row["id"],
        "spaceId": row["space_id"],
        "sourceId": row["source_id"],
        "filePath": row["file_path"],
        "fileName": row["file_name"],
        "fileType": row["file_type"],
        "fileSize": row["file_size"],
        "pageCount": row["page_count"],
        "charCount": row["char_count"],
        "chunkCount": row["chunk_count"],
        "url": _col("url"),
        "title": _col("title") or row["file_name"],
        "section": _col("section"),
        "contentHash": _col("content_hash"),
        "fetchedAt": _col("fetched_at"),
        "generationId": _col("generation_id"),
        "createdAt": row["created_at"],
    }


async def create_rag_document(doc_id: str, space_id: str, source_id: str, file_path: str,
                              file_name: str, file_type: str, file_size: int = 0,
                              page_count: int = 0, char_count: int = 0, chunk_count: int = 0,
                              url: Optional[str] = None, title: Optional[str] = None,
                              section: Optional[str] = None, content_hash: Optional[str] = None,
                              fetched_at: Optional[int] = None,
                              generation_id: Optional[str] = None) -> bool:
    try:
        now = int(time.time() * 1000)
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO rag_documents
                (id, space_id, source_id, file_path, file_name, file_type, file_size,
                 page_count, char_count, chunk_count, url, title, section,
                 content_hash, fetched_at, generation_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (doc_id, space_id, source_id, file_path, file_name, file_type,
                  file_size, page_count, char_count, chunk_count, url, title,
                  section, content_hash, fetched_at, generation_id, now))
        return True
    except Exception as e:
        print(f"Create rag document error: {e}")
        return False


async def get_rag_documents(space_id: str = DEFAULT_SPACE, source_id: Optional[str] = None) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        if source_id:
            rows = await _fetchall(conn,
                'SELECT d.* FROM rag_documents d JOIN rag_sources s '
                'ON s.id = d.source_id AND s.space_id = d.space_id '
                'WHERE d.space_id = ? AND d.source_id = ? '
                'AND ((s.active_generation_id IS NULL AND d.generation_id IS NULL) '
                'OR d.generation_id = s.active_generation_id) '
                'ORDER BY d.file_name',
                (space_id, source_id))
        else:
            rows = await _fetchall(conn,
                'SELECT d.* FROM rag_documents d JOIN rag_sources s '
                'ON s.id = d.source_id AND s.space_id = d.space_id '
                'WHERE d.space_id = ? '
                'AND ((s.active_generation_id IS NULL AND d.generation_id IS NULL) '
                'OR d.generation_id = s.active_generation_id) '
                'ORDER BY d.file_name', (space_id,))
        return [_rag_document_to_dict(r) for r in rows]


async def get_rag_source_counts(source_id: str, space_id: str) -> Dict[str, int]:
    async with get_db() as conn:
        docs = await _fetchone(
            conn, "SELECT COUNT(*) AS n FROM rag_documents WHERE space_id = ? AND source_id = ?",
            (space_id, source_id))
        chunks = await _fetchone(
            conn, "SELECT COUNT(*) AS n FROM rag_chunks WHERE space_id = ? AND source_id = ?",
            (space_id, source_id))
        return {"docCount": int((docs or {"n": 0})["n"]),
                "chunkCount": int((chunks or {"n": 0})["n"])}


async def get_rag_document(doc_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM rag_documents WHERE id = ? AND space_id = ?', (doc_id, space_id))
        return _rag_document_to_dict(row) if row else None


async def update_rag_document(doc_id: str, space_id: str, chunk_count: Optional[int] = None) -> bool:
    """更新文档的切片计数（按空间校验）。"""
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                'UPDATE rag_documents SET chunk_count = ? WHERE id = ? AND space_id = ?',
                (chunk_count, doc_id, space_id))
        return cur.rowcount > 0
    except Exception as e:
        print(f"Update rag document error: {e}")
        return False


async def _fts_table_exists(conn: aiosqlite.Connection) -> bool:
    """FTS 虚表是否存在（无 FTS5 构建上返回 False，调用方静默跳过）。"""
    try:
        row = await _fetchone(
            conn, "SELECT name FROM sqlite_master WHERE type='table' AND name='rag_chunks_fts'")
        return row is not None
    except Exception:
        return False


async def _fts_insert_batch(conn: aiosqlite.Connection,
                            rows: List[Tuple[str, str, str]]) -> None:
    """批量写入 FTS（集合操作，无逐行扫描；表不存在则跳过）。"""
    if not rows or not await _fts_table_exists(conn):
        return
    await conn.executemany(
        'INSERT INTO rag_chunks_fts(content, chunk_id, space_id) VALUES (?, ?, ?)', rows)


async def _fts_delete_by_chunk_ids(conn: aiosqlite.Connection,
                                   space_id: str, ids: List[str]) -> None:
    """按 chunk id 批量删 FTS（每 500 一条语句，避免变量数超限；表不存在则跳过）。"""
    if not ids or not await _fts_table_exists(conn):
        return
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        placeholders = ",".join("?" for _ in part)
        await conn.execute(
            f"DELETE FROM rag_chunks_fts WHERE space_id = ? "
            f"AND chunk_id IN ({placeholders})", [space_id, *part])


async def get_rag_generation_state(
    source_id: str,
    space_id: str,
    generation_id: str,
) -> Dict[str, Any]:
    """Return durable staging progress used to resume an interrupted build."""
    async with get_db() as conn:
        docs = await _fetchall(
            conn,
            "SELECT id, file_path, chunk_count FROM rag_documents "
            "WHERE source_id = ? AND space_id = ? AND generation_id = ?",
            (source_id, space_id, generation_id),
        )
        chunks = await _fetchone(
            conn,
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) AS embedded "
            "FROM rag_chunks WHERE source_id = ? AND space_id = ? AND generation_id = ?",
            (source_id, space_id, generation_id),
        )
        profiles = await _fetchall(
            conn,
            "SELECT DISTINCT embedding_profile_id FROM rag_chunks "
            "WHERE source_id = ? AND space_id = ? AND generation_id = ? "
            "AND embedding_profile_id IS NOT NULL",
            (source_id, space_id, generation_id),
        )
    return {
        "documentCount": len(docs),
        "chunkCount": int((chunks or {"total": 0})["total"] or 0),
        "embeddedCount": int((chunks or {"embedded": 0})["embedded"] or 0),
        "completedPaths": {str(row["file_path"]) for row in docs},
        "profileIds": [str(row["embedding_profile_id"]) for row in profiles],
    }


async def store_rag_document_chunks(
    document: Dict[str, Any],
    chunks: List[Dict[str, Any]],
    space_id: str,
) -> bool:
    """Atomically persist one extracted document and its unembedded chunks.

    A process death can therefore leave either the whole file or none of it;
    the next claimant only has to compare completed ``file_path`` values.
    """
    if not chunks:
        return False
    now = int(time.time() * 1000)
    try:
        async with get_db(busy_timeout_ms=30000) as conn:
            existing = await _fetchone(
                conn,
                "SELECT id FROM rag_documents WHERE id = ? AND space_id = ?",
                (document["id"], space_id),
            )
            if existing:
                return True
            await conn.execute(
                """
                INSERT INTO rag_documents
                (id, space_id, source_id, file_path, file_name, file_type, file_size,
                 page_count, char_count, chunk_count, url, title, section,
                 content_hash, fetched_at, generation_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document["id"], space_id, document["source_id"],
                    document.get("file_path", ""), document.get("file_name", ""),
                    document.get("file_type", ""), int(document.get("file_size") or 0),
                    int(document.get("page_count") or 0), int(document.get("char_count") or 0),
                    len(chunks), document.get("url"), document.get("title"),
                    document.get("section"), document.get("content_hash"),
                    document.get("fetched_at"), document.get("generation_id"), now,
                ),
            )
            fts_rows: List[Tuple[str, str, str]] = []
            for chunk in chunks:
                content = _clean_text_for_db(chunk.get("content", "")) or ""
                await conn.execute(
                    """
                    INSERT INTO rag_chunks
                    (id, space_id, source_id, doc_id, chunk_index, content, page_start, page_end,
                     char_start, char_end, embedding, embedding_profile_id, generation_id,
                     token_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                    """,
                    (
                        chunk["id"], space_id, chunk["source_id"], chunk["doc_id"],
                        int(chunk.get("chunk_index") or 0), content,
                        chunk.get("page_start"), chunk.get("page_end"),
                        chunk.get("char_start"), chunk.get("char_end"),
                        chunk.get("generation_id"), int(chunk.get("token_count") or 0), now,
                    ),
                )
                fts_rows.append((content, chunk["id"], space_id))
            await _fts_insert_batch(conn, fts_rows)
        return True
    except Exception as exc:
        print(f"Store RAG document chunks error: {exc}")
        return False


async def get_pending_rag_chunks(
    source_id: str,
    space_id: str,
    generation_id: str,
    limit: int,
) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            "SELECT id, source_id, content FROM rag_chunks "
            "WHERE source_id = ? AND space_id = ? AND generation_id = ? "
            "AND embedding IS NULL ORDER BY rowid LIMIT ?",
            (source_id, space_id, generation_id, max(1, int(limit))),
        )
        return [dict(row) for row in rows]


async def update_rag_chunk_embeddings(
    space_id: str,
    chunks: List[Dict[str, Any]],
    profile_id: str,
) -> int:
    """Persist one completed embedding batch and its sqlite-vec projection."""
    if not chunks:
        return 0
    updated = 0
    vec_rows: List[Tuple[str, str, str, List[float]]] = []
    vec_dims = 0
    vec_recreated = False
    try:
        async with get_db(busy_timeout_ms=30000) as conn:
            for chunk in chunks:
                embedding = chunk.get("embedding")
                if not isinstance(embedding, list) or not embedding:
                    continue
                cur = await conn.execute(
                    "UPDATE rag_chunks SET embedding = ?, embedding_profile_id = ? "
                    "WHERE id = ? AND space_id = ? AND embedding IS NULL",
                    (json.dumps(embedding, ensure_ascii=False), profile_id, chunk["id"], space_id),
                )
                if cur.rowcount > 0:
                    updated += 1
                    vec_rows.append((chunk["id"], chunk["source_id"], profile_id, embedding))
            vec_dims, vec_recreated = await _vec_dual_write(conn, space_id, vec_rows)
        if vec_dims:
            await _vec_meta_maintain(
                space_id, vec_dims, len(vec_rows), vec_recreated, profile_id)
        return updated
    except Exception as exc:
        print(f"Update RAG chunk embeddings error: {exc}")
        return 0


async def insert_rag_chunks(chunks: List[Dict[str, Any]], space_id: str = DEFAULT_SPACE) -> int:
    """批量写入切片。chunks 元素字段见 rag_chunks 表（embedding 为 list 或 None）。

    FTS 与主表同事务批量同步（无触发器，见 init 迁移注释）。
    向量双写 vec0（P2）：同事务写入含向量的行；扩展缺失/维度异常时静默跳过，
    读路径自动回退暴力检索。
    """
    if not chunks:
        return 0
    now = int(time.time() * 1000)
    try:
        vec_dims = 0
        vec_recreated = False
        async with get_db() as conn:
            fts_rows: List[Tuple[str, str, str]] = []
            vec_rows: List[Tuple[str, str, str, List[float]]] = []
            for ch in chunks:
                content = _clean_text_for_db(ch.get("content", ""))
                await conn.execute('''
                    INSERT INTO rag_chunks
                    (id, space_id, source_id, doc_id, chunk_index, content, page_start, page_end,
                     char_start, char_end, embedding, embedding_profile_id, generation_id,
                     token_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    ch["id"], space_id, ch["source_id"], ch["doc_id"], ch.get("chunk_index", 0),
                    content, ch.get("page_start"), ch.get("page_end"),
                    ch.get("char_start"), ch.get("char_end"),
                    json.dumps(ch["embedding"], ensure_ascii=False) if ch.get("embedding") else None,
                    ch.get("embedding_profile_id"), ch.get("generation_id"),
                    ch.get("token_count", 0), now,
                ))
                fts_rows.append((content, ch["id"], space_id))
                if ch.get("embedding") and ch.get("embedding_profile_id"):
                    vec_rows.append((ch["id"], ch["source_id"],
                                     ch["embedding_profile_id"], ch["embedding"]))
            await _fts_insert_batch(conn, fts_rows)
            vec_dims, vec_recreated = await _vec_dual_write(conn, space_id, vec_rows)
        if vec_dims:
            await _vec_meta_maintain(
                space_id, vec_dims, len(vec_rows), vec_recreated,
                vec_rows[0][2] if vec_rows else None)
        return len(chunks)
    except Exception as e:
        print(f"Insert rag chunks error: {e}")
        return 0


def _vec_store_or_none():
    """懒取 vec_store（无循环导入：backend.server.__init__ 无副作用；缺包回 None）。"""
    try:
        from backend.server import vec_store
        return vec_store if vec_store.available() else None
    except Exception:
        return None


async def _vec_dual_write(conn: aiosqlite.Connection, space_id: str,
                          vec_rows: List[Tuple[str, str, str, List[float]]]
                          ) -> Tuple[int, bool]:
    """vec 双写（必须在外层写事务内调用；只碰 vec 表，不开新连接）。

    返回 (dims, recreated)。元信息维护拆到提交后的 _vec_meta_maintain，
    否则内外两层连接写同一库自死锁（SQLite 锁是库级）。
    失败静默，读路径回退暴力。
    """
    if not vec_rows:
        return 0, False
    vs = _vec_store_or_none()
    if vs is None:
        return 0, False
    try:
        if not await vs.load_extension(conn):
            return 0, False
        dims = len(vec_rows[0][3])
        exists, cur_dims, compatible = await vs.table_state(conn)
        recreated = bool(exists and (cur_dims != dims or not compatible))
        await vs.ensure_table(conn, dims)
        await vs.upsert_batch(conn, space_id, vec_rows)
        return dims, recreated
    except Exception:
        return 0, False


async def _vec_meta_maintain(space_id: str, dims: int, n_written: int,
                             recreated: bool, profile_id: Optional[str] = None) -> None:
    """提交后在新连接上维护元信息（与写事务分离，避免自死锁）。

    * 重建（模型切换）→ 本空间 + 全空间 ready=False（需重新 backfill）；
    * 新空间首次写入 → 计一次数判定覆盖度，全覆盖则 ready=True。
    """
    if not dims:
        return
    try:
        if recreated:
            await set_vec_meta(space_id, dims, False, profile_id)
            try:
                async with get_db() as _c2:
                    await _c2.execute(
                        "UPDATE rag_vec_meta SET ready = 0 WHERE space_id <> ?",
                        (space_id,))
            except Exception:
                pass
            return
        meta = await get_vec_meta(space_id)
        if (meta["dims"] == dims and meta.get("profileId") == profile_id
                and meta["ready"]):
            return
        if meta["dims"] not in (0, dims):
            await set_vec_meta(space_id, dims, False, profile_id)
            return
        try:
            async with get_db() as _c3:
                row = await _fetchone(
                    _c3, "SELECT COUNT(*) AS n FROM rag_chunks"
                         " WHERE space_id = ? AND embedding IS NOT NULL",
                    (space_id,))
                total = row["n"] if row else 0
            # 本批即全部（新空间）→ 直接就绪；否则等 backfill 收尾
            await set_vec_meta(space_id, dims, total <= n_written, profile_id)
        except Exception:
            pass
    except Exception:
        pass


async def get_rag_chunks_for_retrieval(space_id: str = DEFAULT_SPACE,
                                       source_ids: Optional[List[str]] = None,
                                       limit: Optional[int] = None,
                                       after_rowid: int = 0) -> List[Dict[str, Any]]:
    """取某空间（可限定来源）的切片 + 文档元数据，供检索排序。

    返回 list[dict]: id, sourceId, docId, content, embedding(list|None),
    pageStart, pageEnd, fileName, filePath, fileType, url, title。`limit` 用于分页防 OOM。
    """
    async with get_db() as conn:
        if source_ids is not None and len(source_ids) == 0:
            return []
        _has_new_cols = True
        try:
            _cols = await (await conn.execute("PRAGMA table_info(rag_documents)")).fetchall()
            _names = {r["name"] for r in _cols}
            _has_new_cols = {"url", "title"}.issubset(_names)
        except Exception:
            _has_new_cols = False
        _extra = ", d.url, d.title" if _has_new_cols else ", NULL AS url, NULL AS title"
        if source_ids is not None and len(source_ids) > 0:
            placeholders = ",".join("?" for _ in source_ids)
            query = (
                "SELECT c.rowid AS _rowid, c.id, c.source_id, c.doc_id, c.content, c.embedding, "
                "c.embedding_profile_id, c.generation_id, c.page_start, "
                f"c.page_end, d.file_name, d.file_path, d.file_type{_extra} "
                "FROM rag_chunks c LEFT JOIN rag_documents d ON c.doc_id = d.id AND c.space_id = d.space_id "
                "JOIN rag_sources s ON s.id = c.source_id AND s.space_id = c.space_id "
                f"WHERE c.space_id = ? AND c.source_id IN ({placeholders}) "
                "AND c.rowid > ? AND ((s.active_generation_id IS NULL AND c.generation_id IS NULL) "
                "OR c.generation_id = s.active_generation_id)"
            )
            params: List[Any] = [space_id, *source_ids, after_rowid]
        else:
            query = (
                "SELECT c.rowid AS _rowid, c.id, c.source_id, c.doc_id, c.content, c.embedding, "
                "c.embedding_profile_id, c.generation_id, c.page_start, "
                f"c.page_end, d.file_name, d.file_path, d.file_type{_extra} "
                "FROM rag_chunks c LEFT JOIN rag_documents d ON c.doc_id = d.id AND c.space_id = d.space_id "
                "JOIN rag_sources s ON s.id = c.source_id AND s.space_id = c.space_id "
                "WHERE c.space_id = ? AND c.rowid > ? "
                "AND ((s.active_generation_id IS NULL AND c.generation_id IS NULL) "
                "OR c.generation_id = s.active_generation_id)"
            )
            params = [space_id, after_rowid]
        query += " ORDER BY c.rowid"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = await _fetchall(conn, query, params)
        out: List[Dict[str, Any]] = []
        for r in rows:
            emb = None
            if r["embedding"]:
                try:
                    emb = json.loads(r["embedding"])
                except Exception:
                    emb = None
            try:
                _url = r["url"]
            except Exception:
                _url = None
            try:
                _title = r["title"]
            except Exception:
                _title = None
            out.append({
                "id": r["id"],
                "rowId": r["_rowid"],
                "sourceId": r["source_id"],
                "docId": r["doc_id"],
                "content": r["content"],
                "embedding": emb,
                "embeddingProfileId": r["embedding_profile_id"],
                "generationId": r["generation_id"],
                "pageStart": r["page_start"],
                "pageEnd": r["page_end"],
                "fileName": r["file_name"],
                "filePath": r["file_path"],
                "fileType": r["file_type"],
                "url": _url,
                "title": _title,
            })
        return out


async def get_rag_chunks_by_ids(space_id: str = DEFAULT_SPACE,
                                chunk_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """按 chunk id 批量取正文 + 文档元数据（P2 KNN 候选回填；PK 索引，不读向量）。

    返回与 get_rag_chunks_for_retrieval 同形（embedding 恒为 None）。
    """
    if not chunk_ids:
        return []
    try:
        async with get_db() as conn:
            try:
                _cols = await (await conn.execute("PRAGMA table_info(rag_documents)")).fetchall()
                _has_new_cols = {"url", "title"}.issubset({r["name"] for r in _cols})
            except Exception:
                _has_new_cols = False
            _extra = ", d.url, d.title" if _has_new_cols else ", NULL AS url, NULL AS title"
            out: List[Dict[str, Any]] = []
            for i in range(0, len(chunk_ids), 500):
                part = chunk_ids[i:i + 500]
                placeholders = ",".join("?" for _ in part)
                rows = await _fetchall(
                    conn,
                    "SELECT c.id, c.source_id, c.doc_id, c.content, c.page_start, "
                    f"c.page_end, c.embedding_profile_id, c.generation_id, "
                    f"d.file_name, d.file_path, d.file_type{_extra} "
                    "FROM rag_chunks c LEFT JOIN rag_documents d"
                    " ON c.doc_id = d.id AND c.space_id = d.space_id "
                    "JOIN rag_sources s ON s.id = c.source_id AND s.space_id = c.space_id "
                    f"WHERE c.space_id = ? AND c.id IN ({placeholders}) "
                    "AND ((s.active_generation_id IS NULL AND c.generation_id IS NULL) "
                    "OR c.generation_id = s.active_generation_id)",
                    [space_id, *part])
                for r in rows:
                    try:
                        _url = r["url"]
                    except Exception:
                        _url = None
                    try:
                        _title = r["title"]
                    except Exception:
                        _title = None
                    out.append({
                        "id": r["id"],
                        "sourceId": r["source_id"],
                        "docId": r["doc_id"],
                        "content": r["content"],
                        "embedding": None,
                        "embeddingProfileId": r["embedding_profile_id"],
                        "generationId": r["generation_id"],
                        "pageStart": r["page_start"],
                        "pageEnd": r["page_end"],
                        "fileName": r["file_name"],
                        "filePath": r["file_path"],
                        "fileType": r["file_type"],
                        "url": _url,
                        "title": _title,
                    })
            return out
    except Exception:
        return []


async def get_rag_document_by_hash(content_hash: str, space_id: str = DEFAULT_SPACE,
                                   source_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """按内容 hash 查找文档（增量去重用）。无 hash 列的老库返回 None。"""
    if not content_hash:
        return None
    try:
        async with get_db() as conn:
            try:
                _cols = await (await conn.execute("PRAGMA table_info(rag_documents)")).fetchall()
                if "content_hash" not in {r["name"] for r in _cols}:
                    return None
            except Exception:
                return None
            if source_id:
                row = await _fetchone(
                    conn, 'SELECT * FROM rag_documents WHERE space_id = ? AND source_id = ? AND content_hash = ?',
                    (space_id, source_id, content_hash))
            else:
                row = await _fetchone(
                    conn, 'SELECT * FROM rag_documents WHERE space_id = ? AND content_hash = ?',
                    (space_id, content_hash))
            return _rag_document_to_dict(row) if row else None
    except Exception:
        return None


async def get_rag_document_by_url(url: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """按规范化 URL 查找网页文档（粘贴 URL 去重用）。"""
    if not url:
        return None
    try:
        async with get_db() as conn:
            try:
                _cols = await (await conn.execute("PRAGMA table_info(rag_documents)")).fetchall()
                if "url" not in {r["name"] for r in _cols}:
                    return None
            except Exception:
                return None
            row = await _fetchone(
                conn, 'SELECT * FROM rag_documents WHERE space_id = ? AND url = ?', (space_id, url))
            return _rag_document_to_dict(row) if row else None
    except Exception:
        return None


async def delete_rag_document(doc_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除单文档 + 其切片（论文删除级联用）。FTS/vec 显式同步（无触发器）。"""
    try:
        async with get_db() as conn:
            rows = await _fetchall(
                conn, 'SELECT id FROM rag_chunks WHERE doc_id = ? AND space_id = ?',
                (doc_id, space_id))
            ids = [r["id"] for r in rows]
            await _vec_delete_for_conn(conn, space_id, ids)
            await _fts_delete_by_chunk_ids(conn, space_id, ids)
            await conn.execute('DELETE FROM rag_chunks WHERE doc_id = ? AND space_id = ?', (doc_id, space_id))
            cur = await conn.execute('DELETE FROM rag_documents WHERE id = ? AND space_id = ?', (doc_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete rag document error: {e}")
        return False


async def _vec_delete_for_conn(conn: aiosqlite.Connection,
                               space_id: str, ids: List[str]) -> None:
    """同连接删 vec 行（失败静默；读路径以主表为准，孤儿由回填/清理兜底）。"""
    if not ids:
        return
    vs = _vec_store_or_none()
    if vs is None:
        return
    try:
        if await vs.load_extension(conn):
            await vs.delete_by_chunk_ids(conn, space_id, ids)
    except Exception:
        pass


async def ensure_rag_source(source_id: str, space_id: str, name: str, kind: str = "local",
                            target_paths: Any = None, recursive: bool = True,
                            file_types: Any = None) -> Dict[str, Any]:
    """获取或创建系统源（论文库 `__papers__` / 网页 `__web__` 用）。幂等。"""
    if kind not in ("local", "paper", "web"):
        kind = "local"
    existing = await get_rag_source(source_id, space_id)
    if existing:
        return existing
    ok = await create_rag_source(
        source_id, space_id, name, target_paths or [], recursive, file_types or [],
        embedding_model="", status="ready", kind=kind)
    if not ok:
        # 并发创建时另一 worker 已写入，回读即可
        existing = await get_rag_source(source_id, space_id)
        if existing:
            return existing
        raise RuntimeError(f"创建 RAG 系统源失败: {source_id}")
    created = await get_rag_source(source_id, space_id)
    assert created is not None
    return created


def _compile_fts_query(query: str) -> str:
    """把自然语言查询编译为宽松的 FTS5 OR 查询，避免整句精确短语导致零召回。"""
    query = (query or "")[:200]
    latin = re.findall(r"[A-Za-z0-9_]{2,}", query.lower())
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", query)
    terms: List[str] = list(latin)
    for run in cjk_runs:
        if len(run) <= 3:
            terms.append(run)
        else:
            terms.extend(run[i:i + 3] for i in range(len(run) - 2))
    # 去重且限制表达式大小；所有 token 都强制 quote，杜绝 FTS 操作符注入。
    unique = list(dict.fromkeys(t for t in terms if t))[:32]
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in unique)


async def fts_search_chunk_ids(space_id: str, query: str, limit: int = 50,
                               source_ids: Optional[List[str]] = None) -> List[str]:
    """FTS5 BM25 粗排：返回命中的 chunk_id 列表（按 bm25 排序）。无 FTS5 返回 [] 由调用方回退。"""
    query = (query or "").strip()
    if not query:
        return []
    try:
        async with get_db() as conn:
            try:
                row = await _fetchone(
                    conn, "SELECT name FROM sqlite_master WHERE type='table' AND name='rag_chunks_fts'")
                if not row:
                    return []
            except Exception:
                return []
            match_q = _compile_fts_query(query)
            if not match_q:
                return []
            source_sql = ""
            params: List[Any] = [match_q, space_id]
            if source_ids is not None:
                if not source_ids:
                    return []
                placeholders = ",".join("?" for _ in source_ids)
                source_sql = f" AND c.source_id IN ({placeholders})"
                params.extend(source_ids)
            params.append(limit)
            rows = await _fetchall(
                conn,
                "SELECT f.chunk_id FROM rag_chunks_fts f "
                "JOIN rag_chunks c ON c.id = f.chunk_id AND c.space_id = f.space_id "
                "JOIN rag_sources s ON s.id = c.source_id AND s.space_id = c.space_id "
                "WHERE rag_chunks_fts MATCH ? AND f.space_id = ? "
                "AND ((s.active_generation_id IS NULL AND c.generation_id IS NULL) "
                "OR c.generation_id = s.active_generation_id)"
                + source_sql + " ORDER BY rank LIMIT ?",
                params)
            return [r["chunk_id"] for r in rows]
    except Exception:
        return []


async def has_rag_vectors(space_id: str = DEFAULT_SPACE,
                          source_ids: Optional[List[str]] = None) -> bool:
    """某空间（可限定来源）是否存在带向量的切片（EXISTS 语义，命中即停）。

    供检索入口做 any_vec 门：零向量时直接跳过问题嵌入，省 API token 与
    本地模型加载（vec0 行只可能来自含向量的切片，同一门适用）。
    """
    try:
        async with get_db() as conn:
            if source_ids:
                placeholders = ",".join("?" for _ in source_ids)
                row = await _fetchone(
                    conn, "SELECT 1 AS ok FROM rag_chunks WHERE space_id = ?"
                          f" AND source_id IN ({placeholders})"
                          " AND embedding IS NOT NULL LIMIT 1",
                    [space_id, *source_ids])
            else:
                row = await _fetchone(
                    conn, "SELECT 1 AS ok FROM rag_chunks WHERE space_id = ?"
                          " AND embedding IS NOT NULL LIMIT 1",
                    [space_id])
            return row is not None
    except Exception:
        return True  # 判定失败不阻断，按老路走（宁可多调一次）


async def get_rag_retrieval_profile(space_id: str = DEFAULT_SPACE,
                                    source_ids: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """仅当活动语料全部落在同一个已登记向量空间时返回该 profile。"""
    try:
        async with get_db() as conn:
            params: List[Any] = [space_id]
            source_sql = ""
            if source_ids is not None:
                if not source_ids:
                    return None
                placeholders = ",".join("?" for _ in source_ids)
                source_sql = f" AND c.source_id IN ({placeholders})"
                params.extend(source_ids)
            rows = await _fetchall(
                conn,
                "SELECT DISTINCT c.embedding_profile_id AS profile_id FROM rag_chunks c "
                "JOIN rag_sources s ON s.id = c.source_id AND s.space_id = c.space_id "
                "WHERE c.space_id = ? AND c.embedding IS NOT NULL "
                "AND c.embedding_profile_id IS NOT NULL "
                "AND ((s.active_generation_id IS NULL AND c.generation_id IS NULL) "
                "OR c.generation_id = s.active_generation_id)"
                + source_sql + " LIMIT 2",
                params)
            ids = [r["profile_id"] for r in rows if r["profile_id"]]
            if len(rows) != 1 or len(ids) != 1:
                return None
            row = await _fetchone(
                conn, "SELECT * FROM rag_embedding_profiles WHERE id = ?", (ids[0],))
            return dict(row) if row else None
    except Exception:
        return None


async def get_rag_stats(space_id: str = DEFAULT_SPACE) -> Dict[str, int]:
    async with get_db() as conn:
        src = await _fetchone(conn, 'SELECT COUNT(*) AS n FROM rag_sources WHERE space_id = ?', (space_id,))
        docs = await _fetchone(conn,
            'SELECT COUNT(*) AS n FROM rag_documents d JOIN rag_sources s '
            'ON s.id=d.source_id AND s.space_id=d.space_id WHERE d.space_id = ? '
            'AND ((s.active_generation_id IS NULL AND d.generation_id IS NULL) '
            'OR d.generation_id=s.active_generation_id)', (space_id,))
        chunks = await _fetchone(conn,
            'SELECT COUNT(*) AS n FROM rag_chunks c JOIN rag_sources s '
            'ON s.id=c.source_id AND s.space_id=c.space_id WHERE c.space_id = ? '
            'AND ((s.active_generation_id IS NULL AND c.generation_id IS NULL) '
            'OR c.generation_id=s.active_generation_id)', (space_id,))
        vecs = await _fetchone(conn,
            "SELECT COUNT(*) AS n FROM rag_chunks c JOIN rag_sources s "
            "ON s.id=c.source_id AND s.space_id=c.space_id WHERE c.space_id = ? "
            "AND c.embedding IS NOT NULL "
            "AND ((s.active_generation_id IS NULL AND c.generation_id IS NULL) "
            "OR c.generation_id=s.active_generation_id)", (space_id,))
        return {
            "sourceCount": src["n"] if src else 0,
            "docCount": docs["n"] if docs else 0,
            "chunkCount": chunks["n"] if chunks else 0,
            "vectorCount": vecs["n"] if vecs else 0,
        }


def _rag_job_to_dict(row) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    try:
        payload = json.loads(row["payload"]) if row["payload"] else {}
    except Exception:
        payload = {}
    try:
        checkpoint = json.loads(row["checkpoint"]) if row["checkpoint"] else {}
    except Exception:
        checkpoint = {}

    def _job_col(name: str, default=None):
        try:
            value = row[name]
            return default if value is None else value
        except Exception:
            return default

    return {
        "id": row["id"],
        "spaceId": row["space_id"],
        "kind": row["kind"],
        "sourceId": row["source_id"],
        "dedupeKey": row["dedupe_key"] if "dedupe_key" in row.keys() else None,
        "payload": payload,
        "status": row["status"],
        "claimer": row["claimer"],
        "leaseExpiresAt": row["lease_expires_at"],
        "error": row["error"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "generationId": _job_col("generation_id"),
        "phase": _job_col("phase", "queued"),
        "checkpoint": checkpoint,
    }


async def enqueue_rag_index(space_id: str, source_id: str, paths: List[str],
                            recursive: bool, file_types: Any) -> str:
    """本地索引任务入队（同源已有 pending/claimed/running 任务则复用，不重复入队）。

    返回 job_id。调用方（rag_runner.submit_index）入队即返，前端照旧轮询
    rag_sources 状态；真正的执行由各 worker 的 dispatcher 认领后推进。
    """
    return await enqueue_rag_job(
        space_id, source_id, "local_index",
        {"paths": list(paths or []), "recursive": bool(recursive),
         "file_types": list(file_types or [])},
        dedupe_key=f"local:{source_id}",
    )


async def enqueue_rag_job(space_id: str, source_id: str, kind: str,
                          payload: Dict[str, Any], *, dedupe_key: Optional[str] = None) -> str:
    """统一持久队列入口。local/paper/web 均由同一个单写者消费。"""
    if kind not in ("local_index", "paper_index", "web_index"):
        raise ValueError(f"unsupported RAG job kind: {kind}")
    now = int(time.time() * 1000)
    dedupe_key = dedupe_key or f"{kind}:{source_id}:{json.dumps(payload, sort_keys=True)}"
    try:
        async with get_db() as conn:
            row = await _fetchone(
                conn, "SELECT * FROM rag_index_jobs WHERE space_id = ? AND dedupe_key = ?"
                      " AND status IN ('pending','claimed','running')"
                      " ORDER BY created_at DESC LIMIT 1",
                (space_id, dedupe_key))
            if row:
                return row["id"]
            job_id = str(uuid.uuid4())
            await conn.execute('''
                INSERT INTO rag_index_jobs
                (id, space_id, kind, source_id, dedupe_key, payload, status,
                 claimer, lease_expires_at, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL, ?, ?)
            ''', (job_id, space_id, kind, source_id, dedupe_key,
                  json.dumps(payload or {}, ensure_ascii=False),
                  now, now))
            return job_id
    except Exception as e:
        print(f"Enqueue rag index error: {e}")
        raise


async def ensure_rag_job_generation(job_id: str, space_id: str) -> Optional[str]:
    """Assign one immutable staging generation to a job and return it.

    ``COALESCE`` makes repeated calls and crash recovery idempotent: a reclaimed
    job continues writing the same invisible generation instead of starting over.
    """
    candidate = uuid.uuid4().hex
    now = int(time.time() * 1000)
    try:
        async with get_db(busy_timeout_ms=30000) as conn:
            await conn.execute(
                "UPDATE rag_index_jobs SET generation_id = COALESCE(generation_id, ?), "
                "phase = CASE WHEN phase IS NULL OR phase = 'queued' THEN 'discovering' ELSE phase END, "
                "updated_at = ? WHERE id = ? AND space_id = ?",
                (candidate, now, job_id, space_id),
            )
            row = await _fetchone(
                conn,
                "SELECT generation_id FROM rag_index_jobs WHERE id = ? AND space_id = ?",
                (job_id, space_id),
            )
            return str(row["generation_id"]) if row and row["generation_id"] else None
    except Exception as exc:
        print(f"Ensure RAG job generation error: {exc}")
        return None


async def update_rag_job_checkpoint(
    job_id: str,
    space_id: str,
    *,
    phase: str,
    checkpoint: Dict[str, Any],
) -> bool:
    """Persist resumable progress after each file or embedding batch."""
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                "UPDATE rag_index_jobs SET phase = ?, checkpoint = ?, updated_at = ? "
                "WHERE id = ? AND space_id = ? AND status IN ('claimed','running')",
                (
                    phase,
                    json.dumps(checkpoint or {}, ensure_ascii=False),
                    int(time.time() * 1000),
                    job_id,
                    space_id,
                ),
            )
            return cur.rowcount > 0
    except Exception as exc:
        print(f"Update RAG checkpoint error: {exc}")
        return False


async def acquire_rag_worker_lease(worker_id: str, lease_sec: int = 300) -> bool:
    now = int(time.time() * 1000)
    expires = now + lease_sec * 1000
    try:
        async with get_db(busy_timeout_ms=30000) as conn:
            cur = await conn.execute('''
                INSERT INTO rag_worker_lease(name, owner, expires_at, updated_at)
                VALUES ('index-writer', ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,
                    expires_at=excluded.expires_at, updated_at=excluded.updated_at
                WHERE rag_worker_lease.owner = excluded.owner
                   OR rag_worker_lease.expires_at < excluded.updated_at
            ''', (worker_id, expires, now))
            return cur.rowcount > 0
    except Exception:
        return False


async def release_rag_worker_lease(worker_id: str) -> bool:
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                "DELETE FROM rag_worker_lease WHERE name = 'index-writer' AND owner = ?",
                (worker_id,))
            return cur.rowcount > 0
    except Exception:
        return False


async def claim_rag_index_job(worker_id: str, lease_sec: int = 7200) -> Optional[Dict[str, Any]]:
    """原子认领一个待执行任务（单条 UPDATE...RETURNING，跨进程互斥）。

    可认领：pending，或 claimed/running 但租约已过期（执行者崩溃后可被接管）。
    同一时刻全局只有一个认领者拿到任务 → 单写者串行化。
    """
    now = int(time.time() * 1000)
    try:
        async with get_db(busy_timeout_ms=30000) as conn:
            cur = await conn.execute('''
                UPDATE rag_index_jobs SET status = 'claimed', claimer = ?,
                       lease_expires_at = ?, updated_at = ?
                WHERE id = (
                    SELECT id FROM rag_index_jobs
                    WHERE status = 'pending'
                       OR ((status = 'claimed' OR status = 'running')
                           AND (lease_expires_at IS NULL OR lease_expires_at < ?))
                    ORDER BY created_at ASC LIMIT 1
                ) RETURNING *
            ''', (worker_id, now + lease_sec * 1000, now, now))
            row = await cur.fetchone()
            return _rag_job_to_dict(row) if row else None
    except Exception as e:
        # 锁竞争下认领失败 = 别的 worker 正在认领，本轮空转等待下轮
        if _is_locked_error(e):
            return None
        print(f"Claim rag index error: {e}")
        return None


async def mark_rag_job_running(job_id: str, space_id: str) -> bool:
    """任务置 running（执行线程启动后调用，区别“已认领未开工”）。"""
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                "UPDATE rag_index_jobs SET status = 'running', updated_at = ?"
                " WHERE id = ? AND space_id = ? AND status = 'claimed'",
                (int(time.time() * 1000), job_id, space_id))
            return cur.rowcount > 0
    except Exception:
        return False


async def get_rag_index_job(job_id: str, space_id: str) -> Optional[Dict[str, Any]]:
    try:
        async with get_db() as conn:
            row = await _fetchone(
                conn, "SELECT * FROM rag_index_jobs WHERE id = ? AND space_id = ?",
                (job_id, space_id))
            return _rag_job_to_dict(row) if row else None
    except Exception:
        return None


async def renew_rag_job_lease(job_id: str, space_id: str, lease_sec: int = 7200) -> bool:
    """续租（执行中定期调用；任务被取消/改写后返回 False，执行者应停工）。"""
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                "UPDATE rag_index_jobs SET lease_expires_at = ?, updated_at = ?"
                " WHERE id = ? AND space_id = ? AND status IN ('claimed','running')",
                (int(time.time() * 1000) + lease_sec * 1000,
                 int(time.time() * 1000), job_id, space_id))
            return cur.rowcount > 0
    except Exception:
        return False


async def finish_rag_index_job(job_id: str, space_id: str, status: str,
                               error: Optional[str] = None) -> bool:
    """任务落终态（done|failed|cancelled）。"""
    if status not in ("done", "failed", "cancelled"):
        status = "failed"
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                "UPDATE rag_index_jobs SET status = ?, phase = ?, error = ?, updated_at = ?"
                " WHERE id = ? AND space_id = ?"
                " AND (status != 'cancelled' OR ? = 'cancelled')",
                (status, status, error, int(time.time() * 1000), job_id, space_id, status))
            return cur.rowcount > 0
    except Exception:
        return False


async def cancel_rag_index_jobs(space_id: str, source_id: str) -> int:
    """取消某源尚未完成的任务（pending/claimed/running → cancelled），返回条数。

    执行中的认领者通过续租失败或状态轮询感知取消并停工（见 rag_runner）。
    """
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                "UPDATE rag_index_jobs SET status = 'cancelled', phase = 'cancelled', updated_at = ?"
                " WHERE space_id = ? AND source_id = ?"
                " AND status IN ('pending','claimed','running')",
                (int(time.time() * 1000), space_id, source_id))
            return cur.rowcount or 0
    except Exception:
        return 0


async def get_vec_meta(space_id: str = DEFAULT_SPACE) -> Dict[str, Any]:
    """取某空间向量存储元信息（无记录回默认值 ready=0，即暴力检索）。"""
    try:
        async with get_db() as conn:
            row = await _fetchone(
                conn, 'SELECT dims, profile_id, ready, updated_at FROM rag_vec_meta WHERE space_id = ?',
                (space_id,))
            if not row:
                return {"dims": 0, "profileId": None, "ready": False, "updatedAt": 0}
            return {"dims": row["dims"] or 0, "ready": bool(row["ready"]),
                    "profileId": row["profile_id"],
                    "updatedAt": row["updated_at"] or 0}
    except Exception:
        return {"dims": 0, "profileId": None, "ready": False, "updatedAt": 0}


async def set_vec_meta(space_id: str = DEFAULT_SPACE, dims: int = 0,
                       ready: bool = False, profile_id: Optional[str] = None) -> bool:
    """写向量存储元信息（backfill 收尾置 ready=1；维度变化置 ready=0）。"""
    try:
        async with get_db() as conn:
            now = int(time.time() * 1000)
            await conn.execute(
                'INSERT INTO rag_vec_meta (space_id, dims, profile_id, ready, updated_at)'
                ' VALUES (?, ?, ?, ?, ?)'
                ' ON CONFLICT(space_id) DO UPDATE SET dims=excluded.dims,'
                ' profile_id=excluded.profile_id, ready=excluded.ready, updated_at=excluded.updated_at',
                (space_id, dims, profile_id, 1 if ready else 0, now))
            return True
    except Exception:
        return False


__all__ = [
    "_rag_source_to_dict",
    "create_rag_source",
    "update_rag_source",
    "upsert_rag_embedding_profile",
    "get_rag_embedding_profile",
    "activate_rag_generation",
    "clear_rag_generation",
    "get_rag_source",
    "get_rag_sources",
    "delete_rag_source",
    "clear_rag_chunks",
    "_rag_document_to_dict",
    "create_rag_document",
    "get_rag_documents",
    "get_rag_source_counts",
    "get_rag_document",
    "update_rag_document",
    "_fts_table_exists",
    "_fts_insert_batch",
    "_fts_delete_by_chunk_ids",
    "get_rag_generation_state",
    "store_rag_document_chunks",
    "get_pending_rag_chunks",
    "update_rag_chunk_embeddings",
    "insert_rag_chunks",
    "_vec_store_or_none",
    "_vec_dual_write",
    "_vec_meta_maintain",
    "get_rag_chunks_for_retrieval",
    "get_rag_chunks_by_ids",
    "get_rag_document_by_hash",
    "get_rag_document_by_url",
    "delete_rag_document",
    "_vec_delete_for_conn",
    "ensure_rag_source",
    "_compile_fts_query",
    "fts_search_chunk_ids",
    "has_rag_vectors",
    "get_rag_retrieval_profile",
    "get_rag_stats",
    "_rag_job_to_dict",
    "enqueue_rag_index",
    "enqueue_rag_job",
    "ensure_rag_job_generation",
    "update_rag_job_checkpoint",
    "acquire_rag_worker_lease",
    "release_rag_worker_lease",
    "claim_rag_index_job",
    "mark_rag_job_running",
    "get_rag_index_job",
    "renew_rag_job_lease",
    "finish_rag_index_job",
    "cancel_rag_index_jobs",
    "get_vec_meta",
    "set_vec_meta",
]
