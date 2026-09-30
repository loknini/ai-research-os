"""FastAPI 生命周期：恢复状态、初始化持久层并启动后台运行器。"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .. import db
from ..cron_scheduler import start_scheduler, stop_scheduler
from ..development.runner import start_development_runner, stop_development_runner
from ..rag import runner as rag_runner
from ..services.backup import recover_interrupted_import
from .admin_access import startup_security_message
from .health import _INSTANCE_ID
from .instance_guard import beat, heartbeat_loop, list_siblings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """初始化共享资源，并在应用退出时通知后台协程停止。"""
    # Worker 可能在备份导入的两次原子替换之间退出；连接数据库前先恢复日志。
    recover_interrupted_import()
    # 数据库初始化可重复执行，并负责迁移以及 WAL 连接参数。
    await db.init_db()

    security_message = startup_security_message()
    if "WARNING" in security_message:
        logger.warning(security_message)
    else:
        logger.info(security_message)

    # 不同端口的重复后端可能共享同一 SQLite；心跳只告警，不擅自结束其它进程。
    heartbeat_stop: asyncio.Event | None = None
    heartbeat_task: asyncio.Task | None = None
    try:
        beat()
        siblings = list_siblings()
        if siblings:
            logger.error(
                "检测到 %s 个其它后端实例共享同一数据库: %s（本实例 %s）。"
                "请只保留一个，否则可能出现 database is locked。",
                len(siblings),
                [(item.get("supervisorPid"), item.get("port")) for item in siblings],
                _INSTANCE_ID,
            )
        else:
            logger.info("backend.instance_started instance_id=%s siblings=0", _INSTANCE_ID)
        heartbeat_stop = asyncio.Event()
        heartbeat_task = asyncio.create_task(heartbeat_loop(heartbeat_stop))
    except Exception as exc:  # noqa: BLE001 - 心跳失败不能阻断应用启动
        logger.exception("backend.instance_heartbeat_disabled error=%s", exc)

    # Cron 线程、研发运行器和 RAG dispatcher 都自行通过数据库协调多 worker。
    start_scheduler()
    start_development_runner()
    rag_stop = asyncio.Event()
    rag_task = asyncio.create_task(rag_runner.dispatcher(rag_stop))
    try:
        yield
    finally:
        if heartbeat_stop is not None:
            heartbeat_stop.set()
        rag_stop.set()
        stop_development_runner()
        stop_scheduler()

        # 事件循环关闭前等待异步常驻任务真正退出；只设置 Event 而不等待会让
        # aiosqlite 工作线程在已关闭的 loop 上回调，产生 Event loop is closed。
        tasks = [task for task in (heartbeat_task, rag_task) if task is not None]
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=6.0)
            except asyncio.TimeoutError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)


__all__ = ["lifespan"]
