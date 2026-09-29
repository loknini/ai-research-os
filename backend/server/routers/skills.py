"""技能管理 API。

向管理界面暴露由 ``SkillBridge`` 从 ``backend/skills/<name>/SKILL.md`` 构建的技能
注册表，包括列表、运行时重新扫描、启停和直接调用端点。

技能目录是固定的全局配置，因此列表与重新扫描端点不要求 ``space_id``；执行技能时
仍使用当前空间，使其写操作与聊天路径保持一致的隔离语义。
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..deps import get_space_id
from ..core.admin_access import require_admin
from ..skills_bridge import reload_skills, scan_skills, set_skill_enabled
from scripts.chat_agent_stream import execute_tool, is_skill_tool

router = APIRouter(
    prefix="/api/skills",
    tags=["skills"],
    dependencies=[Depends(require_admin)],
)


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
