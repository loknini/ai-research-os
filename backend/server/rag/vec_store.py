"""向量存储层（P2）：sqlite-vec vec0，SQLite 内零服务 KNN。

设计
----
* 单表 ``rag_vec(vec_id TEXT PRIMARY KEY, chunk_id TEXT, space_id TEXT, ... )``；
  ``vec_id`` 是 ``space_id + chunk_id`` 的稳定哈希，避免跨空间同 chunk ID 覆盖。
  查询时按 ``space_id`` (+ ``source_id``)
  预过滤（spike 已验证元数据列可用）。
* 维度 ``D`` 建表时固定（取自首批写入的向量长度）；嵌入模型切换导致维度变化
  时删表重建 + ``ready=0``（需重新 backfill），读路径维度不符自动回退暴力。
* 扩展按连接加载（``get_db()`` 每次新建连接）：``enable_load_extension`` +
  ``select load_extension(path)``（worker 线程内执行，spike 已验证 aiosqlite 可行）。
  未安装 ``sqlite-vec`` 包 → ``available()`` 为假，全链路静默回退旧路径。
* 元信息 ``rag_vec_meta``（见 database.py DDL）：``{dims, ready, updated}``。
  ready=1 仅当表内数据与主表同步（双写持续维护 + backfill 收尾置位）。

调用方：
* 写：``database.insert_rag_chunks`` 内双写（同事务）、``clear_rag_chunks`` /
  ``delete_rag_document`` 内按 id 删；
* 读：``rag_service.retrieve`` 经 ``knn()`` 取候选，再与稀疏 RRF 融合；
* 回填：``scripts/backfill_vec.py``（分批、可断点续跑）。
"""
from __future__ import annotations

import re
import hashlib
from typing import Any, Dict, List, Optional, Tuple
_VEC_TABLE = "rag_vec"

_ext_ok: Optional[bool] = None


def available() -> bool:
    """sqlite-vec 包是否可用（缓存判定）。"""
    global _ext_ok
    if _ext_ok is None:
        try:
            import sqlite_vec  # noqa: F401
            _ext_ok = True
        except Exception:
            _ext_ok = False
    return bool(_ext_ok)


def _loadable_path() -> Optional[str]:
    try:
        import sqlite_vec
        return sqlite_vec.loadable_path()
    except Exception:
        return None


async def load_extension(conn) -> bool:
    """在给定连接上加载 vec0 扩展（worker 线程内执行）。失败返回 False。"""
    if not available():
        return False
    path = _loadable_path()
    if not path:
        return False
    try:
        await conn.execute("select load_extension(?)", (path,))
        return True
    except Exception:
        try:
            await conn.enable_load_extension(True)
            await conn.execute("select load_extension(?)", (path,))
            return True
        except Exception:
            return False


def _existing_dims(conn_rows_sql: Optional[str]) -> Optional[int]:
    if not conn_rows_sql:
        return None
    m = re.search(r"float\[(\d+)\]", conn_rows_sql)
    return int(m.group(1)) if m else None


async def ensure_table(conn, dims: int) -> bool:
    """确保 vec 表存在且维度匹配；维度变化则删表重建（调用方需重置 meta）。"""
    try:
        cur = await conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (_VEC_TABLE,))
        row = await cur.fetchone()
    except Exception:
        return False
    existing_sql = row[0] if row else ""
    cur_dims = _existing_dims(existing_sql)
    ddl = (f"CREATE VIRTUAL TABLE {_VEC_TABLE} USING vec0("
           f"vec_id TEXT PRIMARY KEY, chunk_id TEXT, space_id TEXT, "
           f"source_id TEXT, profile_id TEXT, "
           f"embedding float[{dims}])")
    try:
        compatible = "vec_id TEXT PRIMARY KEY" in existing_sql and "chunk_id TEXT" in existing_sql
        if not row:
            await conn.execute(ddl)
            return True
        if cur_dims != dims or "profile_id" not in existing_sql or not compatible:
            await conn.execute(f"DROP TABLE IF EXISTS {_VEC_TABLE}")
            await conn.execute(ddl)
            return True
        return True
    except Exception:
        return False


def _fmt(vec: List[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def _vec_key(space_id: str, chunk_id: str) -> str:
    material = f"{space_id}\0{chunk_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


async def upsert_batch(conn, space_id: str,
                       rows: List[Tuple]) -> int:
    """批量写入向量（INSERT OR REPLACE，按 chunk_id 幂等）。返回写入数。

    rows 元素为 ``(chunk_id, source_id, vector)``。
    """
    if not rows:
        return 0
    normalized = [
        (row[0], row[1], row[2], row[3]) if len(row) == 4
        else (row[0], row[1], "", row[2])
        for row in rows
    ]
    dims = len(normalized[0][3])
    if not await ensure_table(conn, dims):
        return 0
    try:
        # 纯文本向量写法（spike 已验证；不用 vec_f32 以减少版本差异风险）
        await conn.executemany(
            f"INSERT OR REPLACE INTO {_VEC_TABLE}"
            "(vec_id, chunk_id, space_id, source_id, profile_id, embedding)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(_vec_key(space_id, cid), cid, space_id, src, profile, _fmt(v))
             for cid, src, profile, v in normalized])
        return len(normalized)
    except Exception:
        # 维度混杂等边缘情况：逐条重试，坏条跳过
        n = 0
        for cid, src, profile, v in normalized:
            try:
                await conn.execute(
                    f"INSERT OR REPLACE INTO {_VEC_TABLE}"
                    "(vec_id, chunk_id, space_id, source_id, profile_id, embedding)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (_vec_key(space_id, cid), cid, space_id, src, profile, _fmt(v)))
                n += 1
            except Exception:
                continue
        return n


async def delete_by_chunk_ids(conn, space_id: str, ids: List[str]) -> int:
    """按 chunk id 批量删（集合操作，每 500 一条；无逐行扫描）。"""
    if not ids:
        return 0
    total = 0
    try:
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            placeholders = ",".join("?" for _ in part)
            cur = await conn.execute(
                f"DELETE FROM {_VEC_TABLE} WHERE space_id = ? "
                f"AND chunk_id IN ({placeholders})", [space_id, *part])
            total += cur.rowcount or 0
    except Exception:
        pass
    return total


async def knn(conn, space_id: str, query_vec: List[float],
              k: int = 200, source_ids: Optional[List[str]] = None,
              profile_id: Optional[str] = None) -> List[Tuple[str, float]]:
    """KNN 取候选 ``[(chunk_id, distance)]``（按 distance 升序）。失败回 []。

    ``source_ids`` 非空时做预过滤（小源筛选不饿死）；``[]`` 由调用方前置拦截。
    """
    try:
        if source_ids:
            placeholders = ",".join("?" for _ in source_ids)
            cur = await conn.execute(
                f"SELECT chunk_id, distance FROM {_VEC_TABLE}"
                f" WHERE embedding MATCH ? AND space_id = ?"
                f" AND source_id IN ({placeholders}) AND profile_id = ? AND k = ?",
                (_fmt(query_vec), space_id, *source_ids, profile_id or "", max(1, k)))
        else:
            cur = await conn.execute(
                f"SELECT chunk_id, distance FROM {_VEC_TABLE}"
                " WHERE embedding MATCH ? AND space_id = ? AND profile_id = ? AND k = ?",
                (_fmt(query_vec), space_id, profile_id or "", max(1, k)))
        return [(r[0], float(r[1])) for r in await cur.fetchall()]
    except Exception:
        return []


async def table_dims(conn) -> Optional[int]:
    """当前 vec 表维度（无表回 None）。"""
    try:
        cur = await conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (_VEC_TABLE,))
        row = await cur.fetchone()
        return _existing_dims(row[0] if row else None)
    except Exception:
        return None


async def table_state(conn) -> Tuple[bool, Optional[int], bool]:
    """返回 (exists, dims, schema_compatible)，供调用方判断重建是否令索引失备。"""
    try:
        cur = await conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (_VEC_TABLE,))
        row = await cur.fetchone()
        if not row:
            return False, None, False
        sql = row[0] or ""
        compatible = "vec_id TEXT PRIMARY KEY" in sql and "chunk_id TEXT" in sql
        return True, _existing_dims(sql), compatible
    except Exception:
        return False, None, False


__all__ = ["available", "load_extension", "ensure_table", "upsert_batch",
           "delete_by_chunk_ids", "knn", "table_dims", "table_state"]
