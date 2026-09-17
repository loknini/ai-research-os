#!/usr/bin/env python3
"""vec0 回填脚本（P2）：把存量切片向量从 JSON 搬进 rag_vec，可断点续跑。

原理：按 rowid 分页扫描含向量的切片，跳过 vec 表已有的 chunk_id，
缺失的批量 upsert；收尾为每个覆盖完整的空间置 ready=1。

用法：
    python -m scripts.backfill_vec [space] [batch]

无 space 参数时遍历全部有切片的空间。sqlite-vec 未安装直接退出（读路径
会自动回退暴力，无需回填）。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

if __package__ in (None, ""):
    print("请从项目根目录运行：python -m scripts.backfill_vec [space] [batch]", file=sys.stderr)
    raise SystemExit(2)

from scripts import database as db

BATCH = 500


async def backfill_space(space_id: str, batch: int = BATCH) -> dict:
    from backend.server import vec_store

    if not vec_store.available():
        return {"space": space_id, "skipped": "sqlite-vec 未安装"}
    # 每页独立短事务（长事务 + 尾部跨连接写 meta 会自死锁，见 database._vec_dual_write 注释）
    total = 0
    dims = 0
    dims_changed = False
    profile_id = ""
    last_rowid = 0
    while True:
        async with db.get_db(busy_timeout_ms=30000) as conn:
            if not await vec_store.load_extension(conn):
                return {"space": space_id, "skipped": "扩展加载失败"}
            rows = await db._fetchall(
                conn, "SELECT rowid, id, source_id, embedding, embedding_profile_id FROM rag_chunks"
                      " WHERE space_id = ? AND embedding IS NOT NULL"
                      " AND embedding_profile_id IS NOT NULL AND rowid > ?"
                      " ORDER BY rowid ASC LIMIT ?",
                (space_id, last_rowid, batch))
            if not rows:
                break
            todo = []
            for r in rows:
                last_rowid = r["rowid"]
                try:
                    v = json.loads(r["embedding"])
                except Exception:
                    continue
                if not v:
                    continue
                row_profile = r["embedding_profile_id"] or ""
                if not profile_id:
                    profile_id = row_profile
                if row_profile != profile_id:
                    continue
                if not dims:
                    dims = len(v)
                if len(v) != dims:
                    continue  # 混维度脏数据跳过（读路径维度一致才走 vec）
                todo.append((r["id"], r["source_id"], profile_id, v))
            if todo:
                ensured, recreated = await _ensure(conn, dims)
                if not ensured:
                    return {"space": space_id, "error": "建表失败"}
                if recreated:
                    dims_changed = True
                # 已存在的跳过（断点续跑）
                exist = set()
                for i in range(0, len(todo), 500):
                    part = [t[0] for t in todo[i:i + 500]]
                    ph = ",".join("?" for _ in part)
                    for er in await db._fetchall(
                            conn, f"SELECT chunk_id FROM rag_vec WHERE space_id = ? "
                                  f"AND chunk_id IN ({ph})",
                            [space_id, *part]):
                        exist.add(er["chunk_id"])
                fresh = [t for t in todo if t[0] not in exist]
                if fresh:
                    await vec_store.upsert_batch(conn, space_id, fresh)
                    total += len(fresh)
        print(f"[backfill] {space_id}: +{total} ...", flush=True)
    if dims:
        # 当前空间已完整扫描，因此可直接就绪；若本轮重建了全局 vec 表，其他空间
        # 的派生行已丢失，必须全部标记未就绪并分别重跑。
        await db.set_vec_meta(space_id, dims, True, profile_id)
        if dims_changed:
            try:
                async with db.get_db() as _c2:
                    await _c2.execute(
                        "UPDATE rag_vec_meta SET ready = 0 WHERE space_id <> ?",
                        (space_id,))
            except Exception:
                pass
    return {"space": space_id, "backfilled": total, "dims": dims,
            "ready": bool(dims)}


async def _ensure(conn, dims: int) -> tuple:
    """建表/重建（只碰 vec 表；元信息由调用方在事务外维护）。返回 (ok, recreated)。"""
    from backend.server import vec_store

    exists, cur_dims, compatible = await vec_store.table_state(conn)
    if exists and (cur_dims != dims or not compatible):
        await vec_store.ensure_table(conn, dims)
        return True, True
    await vec_store.ensure_table(conn, dims)
    return True, False


async def main() -> None:
    await db.init_db()
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    batch = int(sys.argv[2]) if len(sys.argv) > 2 else BATCH
    if only:
        spaces = [only]
    else:
        async with db.get_db() as conn:
            rows = await db._fetchall(
                conn, "SELECT DISTINCT space_id FROM rag_chunks")
            spaces = [r["space_id"] for r in rows]
    out = []
    for sp in spaces:
        out.append(await backfill_space(sp, batch))
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
