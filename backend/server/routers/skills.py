"""Skill management API.

Exposes the backend's skill registry (populated by ``SkillBridge`` from
``backend/skills/<name>/SKILL.md``) for the management UI:

* ``GET  /api/skills``          list all skills (incl. disabled) with metadata
* ``POST /api/skills/reload``    re-scan the skills directory at runtime
* ``POST /api/skills/{name}/enabled``  enable/disable a skill (rewrites frontmatter)
* ``POST /api/skills/{name}/run``       invoke a skill directly (reuses ``execute_tool``)

Skills are a **global** config (the directory is fixed), so listing/reloading
endpoints do not enforce ``space_id``. Running a skill, however, uses the current
space so that any writes are isolated consistently with the chat path.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..deps import get_space_id
from ..skills_bridge import reload_skills, scan_skills, set_skill_enabled
from scripts.chat_agent_stream import execute_tool, is_skill_tool

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillEnabledRequest(BaseModel):
    enabled: bool


class SkillRunRequest(BaseModel):
    params: Dict[str, Any] = {}


@router.get("")
async def list_skills() -> Dict[str, Any]:
    """列出全部已发现技能（含禁用项）及其元数据。"""
    return {"success": True, "skills": scan_skills()}


@router.post("/reload")
async def reload() -> Dict[str, Any]:
    """重新扫描技能目录，返回生效的技能数量。"""
    count = reload_skills()
    return {"success": True, "count": count}


@router.post("/{name}/enabled")
async def set_enabled(name: str, req: SkillEnabledRequest) -> Any:
    """启用 / 禁用某技能（改写其 SKILL.md 的 enabled 字段并刷新注册表）。"""
    ok = set_skill_enabled(name, req.enabled)
    if not ok:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"未找到技能: {name}"},
        )
    return {"success": True, "name": name, "enabled": req.enabled}


@router.post("/{name}/run")
async def run_skill(
    name: str, req: SkillRunRequest, space_id: str = Depends(get_space_id)
) -> Any:
    """直接调用某技能（仅限已启用项），返回其执行结果。

    复用 ``chat_agent_stream.execute_tool``，因此工具型技能走 subprocess、
    指令型技能回灌正文，与对话中的行为一致；写入型工具落到当前空间。
    """
    if not is_skill_tool(name):
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"未找到已启用的技能: {name}"},
        )
    result = execute_tool(name, req.params or {}, space_id=space_id)
    return {"success": True, "name": name, "result": result}


__all__ = ["router"]
