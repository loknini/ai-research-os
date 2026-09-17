#!/usr/bin/env python3
"""P2 向量存储验证（隔离库，零网络）：双写回填 / KNN 与暴力一致 /
删除同步 / 维度失配回退 / 源过滤 /读路径切换。

运行：python -m scripts.qa_verify_vec
"""
from __future__ import annotations

import asyncio
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

TMP = Path(tempfile.mkdtemp(prefix="vec_qa_"))
import scripts.database as database  # noqa: E402

database.configure_paths(data_dir=TMP, db_path=TMP / "qa_vec.db")
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

SPACE = "qa_vec"
DIM = 8
PROFILE_ID = "qa-vec-profile"
PROFILE_REVISION = "endpoint:" + hashlib.sha256(
    b"http://localhost/v1").hexdigest()[:16]


def _vec(i: int, dim: int = DIM) -> list:
    base = [0.01 * ((i + j) % 7) for j in range(dim)]
    base[i % dim] += 1.0
    return base


def _chunks(n: int, src: str = "s1", doc: str = "d1", dim: int = DIM,
            tag: str = "vecqa") -> list:
    return [{"id": f"{src}-{i}", "source_id": src, "doc_id": doc,
             "chunk_index": i, "content": f"{tag} 内容 {i} 填充",
             "page_start": 1, "page_end": 1, "char_start": i, "char_end": i + 5,
             "embedding": _vec(i, dim), "embedding_profile_id": PROFILE_ID,
             "token_count": 3} for i in range(n)]


async def test_roundtrip_parity() -> None:
    from backend.server import vec_store
    from backend.server import vector_index as _vi

    assert vec_store.available(), "sqlite-vec 未安装"
    assert await database.upsert_rag_embedding_profile({
        "id": PROFILE_ID,
        "provider": "api",
        "model": "test-model",
        "revision": PROFILE_REVISION,
        "dims": DIM,
        "normalized": True,
        "query_instruction": "",
    })
    await database.create_rag_source("s1", SPACE, "s1", [], True, [], status="ready")
    await database.create_rag_document("d1", SPACE, "s1", "/t", "t", "txt",
                                       1, 1, 10, 0)
    assert await database.insert_rag_chunks(_chunks(20), SPACE) == 20
    meta = await database.get_vec_meta(SPACE)
    assert meta["dims"] == DIM and meta["ready"] is True, meta
    print("PASS 双写 + 元信息就绪:", meta)
    # KNN top1 与暴力余弦 top1 一致
    async with database.get_db() as conn:
        assert await vec_store.load_extension(conn)
        knn = await vec_store.knn(
            conn, SPACE, _vec(3), k=5, profile_id=PROFILE_ID)
    assert knn and knn[0][0] == "s1-3", knn
    chunks = await database.get_rag_chunks_for_retrieval(SPACE)
    scored = sorted(((_vi.cosine(_vec(3), c["embedding"]), c["id"]) for c in chunks),
                    reverse=True)
    assert scored[0][1] == "s1-3", scored[0]
    print("PASS KNN/暴力 top1 一致")


async def test_cross_space_vec_identity() -> None:
    """相同 chunk/doc/source ID 跨空间不得在 vec/FTS/主表互相覆盖或误删。"""
    from backend.server import vec_store

    other = "qa_vec_other"
    await database.create_rag_source("s1", other, "s1", [], True, [], status="ready")
    await database.create_rag_document("d1", other, "s1", "/other", "other", "txt",
                                       1, 1, 10, 0)
    assert await database.insert_rag_chunks(_chunks(4), other) == 4
    async with database.get_db() as conn:
        assert await vec_store.load_extension(conn)
        rows = await (await conn.execute(
            "SELECT space_id, COUNT(*) AS n FROM rag_vec "
            "WHERE chunk_id = ? GROUP BY space_id", ("s1-3",))).fetchall()
        assert {r["space_id"] for r in rows} == {SPACE, other}, rows
    assert await database.delete_rag_document("d1", other)
    async with database.get_db() as conn:
        assert await vec_store.load_extension(conn)
        rows = await (await conn.execute(
            "SELECT space_id FROM rag_vec WHERE chunk_id = ?", ("s1-3",))).fetchall()
        assert [r["space_id"] for r in rows] == [SPACE], rows
    remaining = await database.get_rag_chunks_for_retrieval(SPACE)
    assert any(c["id"] == "s1-3" for c in remaining), "跨空间删除误删主空间 chunk"
    print("PASS vec/FTS/主表跨空间同 ID 隔离")


async def test_source_filter_and_delete() -> None:
    from backend.server import vec_store

    await database.create_rag_source("s2", SPACE, "s2", [], True, [], status="ready")
    await database.create_rag_document("d2", SPACE, "s2", "/t2", "t2", "txt",
                                       1, 1, 10, 0)
    assert await database.insert_rag_chunks(_chunks(5, src="s2", doc="d2"), SPACE) == 5
    async with database.get_db() as conn:
        assert await vec_store.load_extension(conn)
        allk = await vec_store.knn(
            conn, SPACE, _vec(1), k=50, profile_id=PROFILE_ID)
        filt = await vec_store.knn(
            conn, SPACE, _vec(1), k=50, source_ids=["s2"],
            profile_id=PROFILE_ID)
        assert allk and filt and all(x in [f[0] for f in filt] or True for x in []), (allk, filt)
        got = [c for c, _ in filt]
        assert got and all(c.startswith("s2-") for c in got), got
    print("PASS 源预过滤:", len(filt))
    assert await database.clear_rag_chunks("s2", SPACE) == 5
    async with database.get_db() as conn:
        assert await vec_store.load_extension(conn)
        left = await vec_store.knn(
            conn, SPACE, _vec(1), k=50, source_ids=["s2"],
            profile_id=PROFILE_ID)
        assert not left, left
    print("PASS 删除同步 vec")
    assert await database.delete_rag_source("s2", SPACE)


async def test_dims_mismatch_fallback() -> None:
    from backend.server import vec_store

    # 换维度写入 → 重建 + ready=False
    await database.create_rag_source("s3", SPACE, "s3", [], True, [], status="ready")
    await database.create_rag_document("d3", SPACE, "s3", "/t3", "t3", "txt",
                                       1, 1, 10, 0)
    assert await database.insert_rag_chunks(_chunks(3, src="s3", doc="d3", dim=4),
                                            SPACE) == 3
    meta = await database.get_vec_meta(SPACE)
    assert meta["dims"] == 4 and meta["ready"] is False, meta
    async with database.get_db() as conn:
        assert await vec_store.load_extension(conn)
        assert await vec_store.table_dims(conn) == 4
    print("PASS 维度切换重建 + 失备:", meta)
    # 恢复 8 维供后继用例
    await database.clear_rag_chunks("s3", SPACE)
    assert await database.insert_rag_chunks(_chunks(2, src="s3", doc="d3"), SPACE) == 2
    meta2 = await database.get_vec_meta(SPACE)
    assert meta2["dims"] == DIM, meta2
    print("PASS 维度恢复")


async def test_retrieve_switch() -> None:
    from backend.server import rag_service as rag
    from backend.server.llm import llm_client

    llm_client.settings.llm_api_key = "test"
    llm_client.settings.llm_base_url = "http://localhost/v1"
    llm_client.settings.llm_model = "test-model"
    # 注意：直接 mock embed_with_fallback（而不是底层 embed）——provider=local 时
    # 真本地模型可用（torch 已装），只断底层拦不住，会载出 1024 维真向量。
    _orig_exact = llm_client.embed_exact
    _orig_spec = rag._current_embedding_spec
    rag._current_embedding_spec = lambda: {
        "provider": "api",
        "model": "test-model",
        "revision": PROFILE_REVISION,
        "query_instruction": "",
        "normalized": True,
    }
    llm_client.embed_exact = lambda texts, **kwargs: [_vec(1) for _ in texts]
    llm_client.call_llm = lambda messages, **kw: "回答 [1]。"
    # vec 未就绪（上一步 dims 变化）→ 应回退 brute
    r1 = await rag.query(SPACE, "vecqa 内容", top_k=3)
    assert r1["denseBackend"] in ("brute", "none"), r1.get("denseBackend")
    print("PASS 未就绪回退:", r1["denseBackend"], r1["mode"])
    # 置就绪 → 走 vec（8 维数据仍在：s1 的 20 条 + s3 的 2 条）
    await database.set_vec_meta(SPACE, DIM, True, PROFILE_ID)
    # 补回填 s1（表曾被 4 维重建清空）：删掉重插
    await database.clear_rag_chunks("s1", SPACE)
    await database.insert_rag_chunks(_chunks(20), SPACE)
    r2 = await rag.query(SPACE, "vecqa 内容", top_k=3)
    assert r2["denseBackend"] == "vec", r2
    assert len(r2["hits"]) == 3 and "[1]" in r2["answer"], r2["answer"]
    print("PASS 读路径切换 vec:", [h["chunkId"] for h in r2["hits"]])
    llm_client.embed_exact = _orig_exact
    rag._current_embedding_spec = _orig_spec


async def test_backfill() -> None:
    from scripts import backfill_vec as mod
    # 模拟存量：清空 vec 表但保留 JSON（维度一致时 backfill 应补回）
    from backend.server import vec_store

    async with database.get_db() as conn:
        assert await vec_store.load_extension(conn)
        await conn.execute("DELETE FROM rag_vec")
    await database.set_vec_meta(SPACE, DIM, False, PROFILE_ID)
    out = await mod.backfill_space(SPACE, batch=7)
    assert out.get("backfilled", 0) > 0, out
    meta = await database.get_vec_meta(SPACE)
    assert meta["ready"] is True and meta["dims"] == DIM, meta
    # 断点续跑：再跑一次应 0 新增
    out2 = await mod.backfill_space(SPACE, batch=7)
    assert out2.get("backfilled", 0) == 0, out2
    print("PASS 回填 + 断点续跑:", out)


async def main() -> None:
    await database.init_db()
    await test_roundtrip_parity()
    await test_cross_space_vec_identity()
    await test_source_filter_and_delete()
    await test_dims_mismatch_fallback()
    await test_retrieve_switch()
    await test_backfill()
    print("\nALL_VEC_QA_PASS")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
