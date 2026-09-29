#!/usr/bin/env python3
"""RAG 索引单写者队列验证（P1）：入队去重 / 原子认领互斥 / 租约接管 /
取消停工 / dispatcher 端到端（隔离库，零网络）。

运行：python -m scripts.qa_verify_rag_queue
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

TMP = Path(tempfile.mkdtemp(prefix="rag_q_"))
import scripts.database as database  # noqa: E402

database.configure_paths(data_dir=TMP, db_path=TMP / "qa_queue.db")
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

SPACE = "qa_queue"


async def test_dedupe() -> None:
    j1 = await database.enqueue_rag_index(SPACE, "src-1", ["/tmp"], True, ["txt"])
    j2 = await database.enqueue_rag_index(SPACE, "src-1", ["/tmp"], True, ["txt"])
    assert j1 == j2, (j1, j2)
    j3 = await database.enqueue_rag_index(SPACE, "src-2", ["/tmp"], True, ["txt"])
    assert j3 != j1
    print("PASS 入队同源去重")


async def test_mutex_and_lease() -> None:
    # 先排空 test_dedupe 留下的 src-1/src-2（FIFO 顺序验证顺带做）
    d = await database.claim_rag_index_job("worker-D")
    assert d is not None and d["sourceId"] == "src-1", d
    assert await database.finish_rag_index_job(d["id"], SPACE, "done") is True
    e = await database.claim_rag_index_job("worker-E")
    assert e is not None and e["sourceId"] == "src-2", e
    assert await database.finish_rag_index_job(e["id"], SPACE, "done") is True
    print("PASS FIFO 顺序 + 完成")
    # 单 pending 任务：A 拿到后 B 必须空手（互斥）；租约过期后 C 可接管
    j = await database.enqueue_rag_index(SPACE, "src-m", ["/tmp"], True, ["txt"])
    a = await database.claim_rag_index_job("worker-A")
    assert a is not None and a["id"] == j, (a, j)
    b = await database.claim_rag_index_job("worker-B")
    assert b is None, f"互斥失败：B 也拿到了 {b}"
    print("PASS 原子认领互斥")
    # 租约过期可被接管：直接把租约写成过去，再认领
    async with database.get_db() as _conn:
        await _conn.execute(
            "UPDATE rag_index_jobs SET lease_expires_at = ? WHERE id = ?",
            (0, j))
    c = await database.claim_rag_index_job("worker-C")
    assert c is not None and c["id"] == j, c
    print("PASS 租约过期接管")
    assert await database.mark_rag_job_running(c["id"], SPACE) is True
    assert await database.renew_rag_job_lease(c["id"], SPACE) is True
    assert await database.finish_rag_index_job(c["id"], SPACE, "done") is True
    assert await database.claim_rag_index_job("worker-Z") is None, "队列应已清空"
    print("PASS 续租/完成/队列清空")


async def test_cancel() -> None:
    j = await database.enqueue_rag_index(SPACE, "src-3", ["/tmp"], True, ["txt"])
    assert await database.mark_rag_job_running(j, SPACE) is False  # 未认领不能 running
    got = await database.claim_rag_index_job("worker-E")
    assert got and got["id"] == j
    assert await database.mark_rag_job_running(j, SPACE) is True
    n = await database.cancel_rag_index_jobs(SPACE, "src-3")
    assert n == 1, n
    assert await database.renew_rag_job_lease(j, SPACE) is False, "取消后续租应失败"
    assert await database.finish_rag_index_job(j, SPACE, "cancelled") is True
    assert await database.claim_rag_index_job("worker-F") is None
    print("PASS 取消→续租失败→终态")


async def test_dispatcher_e2e() -> None:
    from backend.server.rag import runner as rag_runner

    corpus = TMP / "corpus"
    corpus.mkdir(exist_ok=True)
    (corpus / "a.txt").write_text("单写者队列端到端测试内容。", encoding="utf-8")
    (corpus / "b.txt").write_text("第二篇文档，用于验证认领执行。", encoding="utf-8")
    sid = "src-e2e"
    await database.create_rag_source(sid, SPACE, "e2e", [str(corpus)], True,
                                     ["txt"], status="indexing", kind="local")
    await rag_runner.submit_index(sid, SPACE, [str(corpus)], True, ["txt"])
    stop = asyncio.Event()

    async def _run():
        await rag_runner.dispatcher(stop)

    task = asyncio.create_task(_run())
    try:
        deadline = time.time() + 90
        src = None
        while time.time() < deadline:
            await asyncio.sleep(1)
            src = await database.get_rag_source(sid, SPACE)
            if src and src.get("status") in ("ready", "partial", "failed"):
                break
        assert src and src.get("status") in ("ready", "partial"), src
        assert src.get("chunkCount", 0) > 0, src
        assert src.get("progress") == 100, src
        print("PASS dispatcher 端到端:", src["status"], src["chunkCount"], "切片")
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=10)


async def main() -> None:
    await database.init_db()
    await test_dedupe()
    await test_mutex_and_lease()
    await test_cancel()
    await test_dispatcher_e2e()
    print("\nALL_RAG_QUEUE_QA_PASS")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
