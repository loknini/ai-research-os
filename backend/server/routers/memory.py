"""持久记忆管理路由。

* ``GET  /api/memory``        —— 读取当前空间的记忆全文
* ``PUT  /api/memory``        —— 整体覆盖（用户手动编辑）
* ``POST /api/memory/observe``—— 追加一条记忆
* ``POST /api/memory/extract``—— 从一段对话文本中由 LLM 提炼事实并追加（自动沉淀）

空间隔离：从 ``X-Space-Key`` 头解析，与项目其余数据一致。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..deps import get_space_id
from .. import memory as mem

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("")
async def get_memory(space_id: str = Depends(get_space_id)):
    return {"success": True, "space_id": space_id, "content": mem.load_memory(space_id)}


@router.put("")
async def put_memory(req: Request, space_id: str = Depends(get_space_id)):
    try:
        body = await req.json()
        text = body.get("content", "")
    except Exception:
        return JSONResponse(status_code=400, content={"success": False, "error": "INVALID_BODY"})
    ok = mem.save_memory(space_id, text)
    return {"success": ok, "space_id": space_id}


@router.post("/observe")
async def observe_memory(req: Request, space_id: str = Depends(get_space_id)):
    try:
        body = await req.json()
        entry = body.get("entry", "")
    except Exception:
        return JSONResponse(status_code=400, content={"success": False, "error": "INVALID_BODY"})
    ok = mem.append_memory(space_id, entry)
    return {"success": ok, "space_id": space_id, "content": mem.load_memory(space_id)}


@router.post("/extract")
async def extract_memory(req: Request, space_id: str = Depends(get_space_id)):
    """从 ``messages`` 字段（[{role,content}]）中由 LLM 提炼事实并追加到记忆。"""
    try:
        body = await req.json()
        messages = body.get("messages", [])
    except Exception:
        return JSONResponse(status_code=400, content={"success": False, "error": "INVALID_BODY"})
    if not isinstance(messages, list) or not messages:
        return JSONResponse(status_code=400, content={"success": False, "error": "EMPTY_MESSAGES"})

    facts = mem.extract_facts(messages, space_id=space_id)
    if facts is None:
        return {"success": False, "error": "LLM 不可用或无需记忆", "space_id": space_id}
    ok = mem.append_memory(space_id, facts)
    return {"success": ok, "space_id": space_id, "extracted": facts, "content": mem.load_memory(space_id)}


__all__ = ["router"]
