"""RAG 后台索引 runner（不阻塞请求）。

与 ``agent_runner`` 同构：索引是 I/O + 网络密集操作，放进守护线程，线程内自建
asyncio 事件循环跑 DB 写入。``submit_index`` 立即返回 ``source_id``，前端轮询
``rag_sources`` 状态即可看到进度；``cancel_index`` 通过内存 Event + DB 状态双重
取消（跨 worker 也能生效）。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Dict, List, Optional

from . import db
from . import rag_service

# 同 worker 内的即时取消信号；跨 worker 以 DB 状态为准。
RUN_CANCEL: Dict[str, threading.Event] = {}


async def submit_index(
    source_id: str,
    space_id: str,
    paths: List[str],
    recursive: bool,
    file_types: Optional[List[str]],
    embedding_model: Optional[str] = None,
) -> str:
    """提交一次后台索引：落库即返回 source_id，执行在守护线程异步推进。"""
    RUN_CANCEL[source_id] = threading.Event()
    _spawn(source_id, space_id, paths, recursive, file_types, embedding_model)
    return source_id


async def cancel_index(source_id: str, space_id: str) -> bool:
    """取消一次索引：同 worker 置 Event，并落库（跨 worker 也生效）。"""
    ev = RUN_CANCEL.get(source_id)
    if ev is not None:
        ev.set()
    # 后台线程每文件前会检查 DB 状态；这里先把状态写 cancelled，确保跨 worker 生效。
    return await db.database.update_rag_source(source_id, space_id, status="cancelled")


def _spawn(source_id: str, space_id: str, paths: List[str], recursive: bool,
           file_types: Optional[List[str]], embedding_model: Optional[str]) -> None:
    t = threading.Thread(
        target=_worker,
        args=(source_id, space_id, paths, recursive, file_types, embedding_model),
        name=f"rag-index-{source_id[:8]}",
        daemon=True,
    )
    t.start()


def _worker(source_id: str, space_id: str, paths: List[str], recursive: bool,
            file_types: Optional[List[str]], embedding_model: Optional[str]) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_execute(source_id, space_id, paths, recursive,
                                          file_types, embedding_model))
    except Exception as exc:  # noqa: BLE001 - 兜底，避免线程静默崩
        print(f"[rag_runner] worker crashed for {source_id}: {exc}")
        try:
            loop.run_until_complete(
                db.database.update_rag_source(source_id, space_id, status="failed",
                                              error=f"内部错误：{exc}"))
        except Exception:  # noqa: BLE001
            pass
    finally:
        loop.close()
        RUN_CANCEL.pop(source_id, None)


async def _execute(source_id: str, space_id: str, paths: List[str], recursive: bool,
                   file_types: Optional[List[str]], embedding_model: Optional[str]) -> None:
    cancel_ev = RUN_CANCEL.get(source_id)
    await rag_service.index_source(
        source_id, space_id, paths, recursive, file_types,
        embedding_model=embedding_model, cancel_event=cancel_ev)


__all__ = ["submit_index", "cancel_index", "RUN_CANCEL"]
