"""Health & LLM status endpoints."""
from __future__ import annotations

import asyncio
import os
import time

from fastapi import APIRouter

from . import config
from .llm import llm_client
from .utils import mask_key

router = APIRouter(tags=["health"])

# 实例标识：pid + 进程启动时间。重复启动后端时，调两遍 /api/healthz
# 若 instanceId 不同，即存在双实例写同一库（SQLite 锁竞争的头号来源）。
_INSTANCE_ID = f"{os.getpid()}@{int(time.time() * 1000)}"

# /api/llm/status 由设置页「测试连接」按需触发，是对外部 LLM 的依赖检查，
# 用 30s TTL 缓存避免重复外网探测。healthz 只确认进程存活，不触碰任何
# 外部依赖，因此瞬时返回、永不阻塞事件循环。
_REACH_TTL = 30.0
_reach_cache: dict = {"ts": 0.0, "val": False}


def _reachable_cached() -> bool:
    now = time.monotonic()
    if now - _reach_cache["ts"] < _REACH_TTL:
        return _reach_cache["val"]
    val = llm_client._reachable()
    _reach_cache["ts"] = now
    _reach_cache["val"] = val
    return val


@router.get("/api/healthz")
async def healthz() -> dict:
    """Liveness probe: 仅确认后端进程存活，零外部依赖，瞬时返回。

    附带 ``instanceId``（pid@启动毫秒）与 ``siblingInstances``（同 DB 的其它
    supervisor 心跳）：短时间内多次调用若出现超出 worker 数的不同 ID，
    即存在重复后端实例（SQLite 锁竞争之源）。
    """
    try:
        from .instance_guard import list_siblings
        siblings = list_siblings()
    except Exception:
        siblings = []
    return {
        "success": True,
        "status": "ok",
        "version": "0.5.0",
        "instanceId": _INSTANCE_ID,
        "siblingInstances": siblings,
        "db": {
            "path": str(config.DB_PATH),
            "exists": config.DB_PATH.exists(),
        },
    }


@router.get("/api/llm/status")
async def llm_status() -> dict:
    """Detailed LLM configuration / reachability (on-demand, non-blocking)."""
    reachable = await asyncio.to_thread(_reachable_cached)
    s = config.settings
    return {
        "success": True,
        "configured": llm_client.configured,
        "reachable": reachable,
        "baseUrl": s.llm_base_url,
        "model": s.llm_model,
        "apiKeyMasked": mask_key(s.llm_api_key),
    }


__all__ = ["router"]
