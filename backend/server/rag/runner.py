"""RAG 后台索引 runner（P1 单写者队列，不阻塞请求）。

架构（与 cron_scheduler 的原子领取同构）：
* ``submit_index`` 只做入队（同源去重），立即返回 ``source_id``；
  前端照旧轮询 ``rag_sources`` 状态 → 进度/完成，契约不变。
* 每个 worker 的 lifespan 起一个 ``dispatcher`` 协程；先竞争数据库中的全局
  writer lease，持有者才能认领任务，再把重活放进线程。全局始终只有一个执行者；
  分批小事务 + ``with_busy_retry`` 只留作保险。
* job 与 writer lease 均为 300s，dispatcher 每 5s 续租；进程崩溃后可被接管。
* local 重建写入独立 generation，完成后原子切换 active generation；崩溃、取消、
  写入失败都只清理未激活的新代，旧索引持续可用。
* 取消：``cancel_index`` 写 DB；dispatcher 监控 DB 状态并置线程 Event。
* local / paper / web 三类任务统一进入持久队列，避免路由旁路直接写库。
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from typing import Dict, List, Optional

from .. import db
from . import service as rag_service

logger = logging.getLogger(__name__)

# 同 worker 内的即时取消信号；跨 worker 以 DB 状态为准。
RUN_CANCEL: Dict[str, threading.Event] = {}

_WORKER_ID = f"rag-{os.getpid()}-{uuid.uuid4().hex[:8]}"
_DISPATCH_INTERVAL_SEC = 2.0
# 执行者崩溃后最多约 5 分钟由其它 worker 接管。
_LEASE_SEC = 300


async def submit_index(
    source_id: str,
    space_id: str,
    paths: List[str],
    recursive: bool,
    file_types: Optional[List[str]],
) -> str:
    """提交一次后台索引：入队即返回 source_id，执行由 dispatcher 认领推进。"""
    await db.database.enqueue_rag_index(space_id, source_id, paths, recursive, file_types)
    return source_id


async def submit_paper(paper_id: str, space_id: str) -> str:
    source = await rag_service.ensure_paper_source(space_id)
    await db.database.update_rag_source(
        source["id"], space_id, status="indexing", error="")
    return await db.database.enqueue_rag_job(
        space_id, source["id"], "paper_index", {"paper_id": paper_id},
        dedupe_key=f"paper:{paper_id}")


async def submit_web(urls: List[str], space_id: str) -> str:
    normalized = [rag_service.normalize_url(u) for u in urls]
    normalized = [u for u in normalized if u]
    if not normalized:
        raise ValueError("没有可索引的合法公网 http(s) URL")
    source = await rag_service.ensure_web_source(space_id)
    await db.database.update_rag_source(
        source["id"], space_id, status="indexing", error="")
    return await db.database.enqueue_rag_job(
        space_id, source["id"], "web_index", {"urls": normalized},
        dedupe_key="web:" + "|".join(sorted(normalized)))


async def cancel_index(source_id: str, space_id: str) -> bool:
    """取消一次索引：同 worker 置 Event，并落库（跨 worker 也生效）。

    执行线程的 DB 轮询会把 DB 状态同步到内存 Event，正在跑的任务停工；
    还没开工的任务直接标 cancelled，dispatcher 跳过。
    """
    ev = RUN_CANCEL.get(source_id)
    if ev is not None:
        ev.set()
    n = await db.database.cancel_rag_index_jobs(space_id, source_id)
    ok = await db.database.update_rag_source(source_id, space_id, status="cancelled")
    return bool(ok or n)


async def dispatcher(stop: asyncio.Event) -> None:
    """常驻循环；先取得全局 writer lease，再认领并执行一个持久任务。"""
    while not stop.is_set():
        owns_writer = await db.database.acquire_rag_worker_lease(
            _WORKER_ID, lease_sec=_LEASE_SEC)
        if not owns_writer:
            try:
                await asyncio.wait_for(stop.wait(), timeout=_DISPATCH_INTERVAL_SEC)
            except asyncio.TimeoutError:
                pass
            continue
        try:
            job = await db.database.claim_rag_index_job(_WORKER_ID, lease_sec=_LEASE_SEC)
        except Exception as exc:  # noqa: BLE001 - 认领失败本轮跳过
            logger.exception("rag.claim_failed error=%s", exc)
            job = None
        if job is None:
            await db.database.release_rag_worker_lease(_WORKER_ID)
            try:
                await asyncio.wait_for(stop.wait(), timeout=_DISPATCH_INTERVAL_SEC)
            except asyncio.TimeoutError:
                pass
            continue
        # 开工前校验：源被删了 → 任务直接失败；源已取消 → 跳过执行
        try:
            _src = await db.database.get_rag_source(
                job.get("sourceId") or "", job.get("spaceId") or "")
        except Exception:
            _src = None
        if _src is None:
            try:
                await db.database.finish_rag_index_job(
                    job["id"], job.get("spaceId") or "", "failed", "索引源不存在")
            except Exception:
                pass
            await db.database.release_rag_worker_lease(_WORKER_ID)
            continue
        if _src.get("status") == "cancelled":
            try:
                await db.database.finish_rag_index_job(
                    job["id"], job.get("spaceId") or "", "cancelled")
            except Exception:
                pass
            await db.database.release_rag_worker_lease(_WORKER_ID)
            continue
        cancel_ev = threading.Event()
        source_id = job.get("sourceId") or ""
        RUN_CANCEL[source_id] = cancel_ev
        space_id = job.get("spaceId") or ""
        try:
            if not await db.database.mark_rag_job_running(job["id"], space_id):
                continue
            generation_id = await db.database.ensure_rag_job_generation(job["id"], space_id)
            if not generation_id:
                raise RuntimeError("无法为索引任务分配持久 generation")
            job["generationId"] = generation_id
            task = asyncio.create_task(asyncio.to_thread(_run_job_blocking, job, cancel_ev))
            while not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                if task.done():
                    break
                if stop.is_set():
                    cancel_ev.set()
                job_ok = await db.database.renew_rag_job_lease(
                    job["id"], space_id, _LEASE_SEC)
                writer_ok = await db.database.acquire_rag_worker_lease(
                    _WORKER_ID, lease_sec=_LEASE_SEC)
                current = await db.database.get_rag_index_job(job["id"], space_id)
                if (not job_ok or not writer_ok or not current
                        or current.get("status") == "cancelled"):
                    cancel_ev.set()
            result = await task
            result_status = (result or {}).get("status", "failed")
            final = ("done" if result_status in ("ready", "partial")
                     else "cancelled" if result_status == "cancelled" else "failed")
            await db.database.finish_rag_index_job(
                job["id"], space_id, final,
                None if final != "failed" else str((result or {}).get("error") or "索引失败")[:200])
        except Exception as exc:  # noqa: BLE001 - 单任务崩溃不杀 dispatcher
            logger.exception("rag.job_crashed job_id=%s error=%s", job.get("id"), exc)
            await db.database.finish_rag_index_job(
                job["id"], space_id, "failed", str(exc)[:200])
        finally:
            cancel_ev.set()
            RUN_CANCEL.pop(source_id, None)
            await db.database.release_rag_worker_lease(_WORKER_ID)


def _run_job_blocking(job: Dict, cancel_ev: threading.Event) -> Dict:
    """线程内只运行索引协程；续租/取消监控全部留在 dispatcher 的事件循环。"""
    space_id = job.get("spaceId") or ""
    payload = job.get("payload") or {}
    source_id = job.get("sourceId") or ""
    kind = job.get("kind") or "local_index"
    if kind == "paper_index":
        return asyncio.run(rag_service.index_paper(payload.get("paper_id") or "", space_id))
    if kind == "web_index":
        return asyncio.run(rag_service.index_urls(payload.get("urls") or [], space_id))
    return asyncio.run(rag_service.index_source(
        source_id, space_id, payload.get("paths") or [],
        bool(payload.get("recursive", True)), payload.get("file_types"),
        cancel_event=cancel_ev, job_id=job.get("id"),
        generation_id=job.get("generationId"),
        checkpoint=job.get("checkpoint") or {}))


__all__ = ["submit_index", "submit_paper", "submit_web", "cancel_index",
           "dispatcher", "RUN_CANCEL"]
