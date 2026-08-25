"""Health & LLM status endpoints."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter

from . import config
from .llm import llm_client
from .utils import mask_key

router = APIRouter(tags=["health"])

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
    """Liveness probe: 仅确认后端进程存活，零外部依赖，瞬时返回。"""
    return {
        "success": True,
        "status": "ok",
        "version": "0.1.0",
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
