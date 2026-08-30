"""Multi-Agent collaboration routes.

The Agent system runs in the **background** (non-blocking):

  POST /api/agent/runs             -> 落库即返 run_id（非阻塞）
  GET  /api/agent/runs             -> 运行列表
  GET  /api/agent/runs/{id}        -> 运行详情 + 事件
  GET  /api/agent/runs/{id}/stream -> DB 轮询式 SSE 进度（跨 worker 安全）
  POST /api/agent/runs/{id}/cancel -> 取消

Session CRUD (backed by ``scripts/database.py``, scoped to ``space_id``) and the
background runner (``backend.server.agent_runner``) are the only surfaces left.
The legacy one-shot SSE endpoints ``/api/agent/run`` and ``/api/agent/collaborate``
were removed on 2026-07-31.
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from .. import db, agent_runner, agent_teams
from ..deps import get_space_id
from ..errors import SSE_DONE, sse_error, APIError
from ..schemas import AgentRunRequest, SessionCreate, ApprovalDecision

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/sessions")
async def create_session(req: SessionCreate, space_id: str = Depends(get_space_id)):
    try:
        session = await db.database.create_agent_session(
            req.projectId, req.sessionType, req.inputData, space_id=space_id
        )
        return {"success": True, "session": session}
    except Exception as exc:
        raise APIError(str(exc), code="CREATE_SESSION_FAILED")


@router.get("/sessions")
async def list_sessions(projectId: Optional[str] = None, space_id: str = Depends(get_space_id)):
    try:
        sessions = await db.database.get_agent_sessions(projectId, space_id=space_id)
        return {"success": True, "sessions": sessions}
    except Exception as exc:
        raise APIError(str(exc), code="LIST_SESSIONS_FAILED")


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, space_id: str = Depends(get_space_id)):
    try:
        messages = await db.database.get_agent_messages(session_id, space_id=space_id)
        return {"success": True, "messages": messages}
    except Exception as exc:
        raise APIError(str(exc), code="GET_MESSAGES_FAILED")


# ---------------------------------------------------------------------------
# Configurable expert teams
# ---------------------------------------------------------------------------
@router.get("/teams")
async def list_teams(space_id: str = Depends(get_space_id)):
    return {"success": True, "teams": await agent_teams.list_teams(space_id)}


@router.post("/teams")
async def create_team(payload: dict, space_id: str = Depends(get_space_id)):
    try:
        definition, warnings = agent_teams.validate_team(payload)
        definition.pop("id", None)
        team = await db.database.create_agent_team(definition, space_id)
        return {"success": True, "team": team, "warnings": warnings}
    except agent_teams.TeamValidationError as exc:
        raise APIError(str(exc), code="INVALID_TEAM", status_code=400)


@router.post("/teams/import")
async def import_team(payload: dict, space_id: str = Depends(get_space_id)):
    try:
        source = payload.get("team", payload)
        definition, warnings = agent_teams.validate_team(source)
        definition.pop("id", None)
        definition["name"] = await agent_teams.unique_team_name(definition["name"], space_id)
        team = await db.database.create_agent_team(definition, space_id)
        return {"success": True, "team": team, "warnings": warnings}
    except agent_teams.TeamValidationError as exc:
        raise APIError(str(exc), code="INVALID_TEAM_IMPORT", status_code=400)


@router.get("/teams/{team_id}")
async def get_team(team_id: str, space_id: str = Depends(get_space_id)):
    team = await agent_teams.resolve_team(team_id, space_id)
    if not team:
        raise APIError("team not found", code="NOT_FOUND", status_code=404)
    return {"success": True, "team": team}


@router.put("/teams/{team_id}")
async def update_team(team_id: str, payload: dict, space_id: str = Depends(get_space_id)):
    if team_id.startswith("builtin-"):
        raise APIError("built-in teams are read-only", code="READ_ONLY", status_code=403)
    try:
        definition, warnings = agent_teams.validate_team(payload)
        definition.pop("id", None)
        team = await db.database.update_agent_team(team_id, definition, space_id)
        if not team:
            raise APIError("team not found", code="NOT_FOUND", status_code=404)
        return {"success": True, "team": team, "warnings": warnings}
    except agent_teams.TeamValidationError as exc:
        raise APIError(str(exc), code="INVALID_TEAM", status_code=400)


@router.delete("/teams/{team_id}")
async def delete_team(team_id: str, space_id: str = Depends(get_space_id)):
    if team_id.startswith("builtin-"):
        raise APIError("built-in teams are read-only", code="READ_ONLY", status_code=403)
    if not await db.database.delete_agent_team(team_id, space_id):
        raise APIError("team not found", code="NOT_FOUND", status_code=404)
    return {"success": True}


@router.post("/teams/{team_id}/clone")
async def clone_team(team_id: str, space_id: str = Depends(get_space_id)):
    source = await agent_teams.resolve_team(team_id, space_id)
    if not source:
        raise APIError("team not found", code="NOT_FOUND", status_code=404)
    return {"success": True, "team": await agent_teams.clone_team(source, space_id)}


@router.get("/teams/{team_id}/export")
async def export_team(team_id: str, space_id: str = Depends(get_space_id)):
    source = await agent_teams.resolve_team(team_id, space_id)
    if not source:
        raise APIError("team not found", code="NOT_FOUND", status_code=404)
    team = {key: value for key, value in source.items()
            if key not in {"builtin", "warnings", "createdAt", "updatedAt"}}
    return JSONResponse(
        {"schemaVersion": 1, "kind": "agent-team", "team": team},
        headers={"Content-Disposition": f'attachment; filename="{team_id}.json"'})


def _validate_role_template(payload: dict) -> dict:
    try:
        return agent_teams.validate_role_template(payload)
    except agent_teams.TeamValidationError as exc:
        raise APIError(str(exc), code="INVALID_ROLE_TEMPLATE", status_code=400)


@router.get("/role-templates")
async def list_role_templates(space_id: str = Depends(get_space_id)):
    custom = await db.database.list_agent_role_templates(space_id)
    return {"success": True, "roleTemplates": agent_teams.list_builtin_role_templates() + custom}


@router.post("/role-templates")
async def create_role_template(payload: dict, space_id: str = Depends(get_space_id)):
    role = _validate_role_template(payload)
    return {"success": True,
            "roleTemplate": await db.database.create_agent_role_template(role, space_id)}


@router.put("/role-templates/{template_id}")
async def update_role_template(template_id: str, payload: dict,
                               space_id: str = Depends(get_space_id)):
    if template_id.startswith("builtin-"):
        raise APIError("built-in role templates are read-only", code="READ_ONLY", status_code=403)
    role = await db.database.update_agent_role_template(
        template_id, _validate_role_template(payload), space_id)
    if not role:
        raise APIError("role template not found", code="NOT_FOUND", status_code=404)
    return {"success": True, "roleTemplate": role}


@router.delete("/role-templates/{template_id}")
async def delete_role_template(template_id: str, space_id: str = Depends(get_space_id)):
    if template_id.startswith("builtin-"):
        raise APIError("built-in role templates are read-only", code="READ_ONLY", status_code=403)
    if not await db.database.delete_agent_role_template(template_id, space_id):
        raise APIError("role template not found", code="NOT_FOUND", status_code=404)
    return {"success": True}


@router.post("/role-templates/{template_id}/clone")
async def clone_role_template(template_id: str, space_id: str = Depends(get_space_id)):
    if template_id.startswith("builtin-"):
        source = next((role for role in agent_teams.list_builtin_role_templates()
                       if role["id"] == template_id), None)
    else:
        source = await db.database.get_agent_role_template(template_id, space_id)
    if not source:
        raise APIError("role template not found", code="NOT_FOUND", status_code=404)
    names = {role["name"] for role in await db.database.list_agent_role_templates(space_id)}
    role = _validate_role_template(source)
    base = f"{role['name']} 副本"
    role["name"] = base
    suffix = 2
    while role["name"] in names:
        role["name"] = f"{base} {suffix}"
        suffix += 1
    return {"success": True,
            "roleTemplate": await db.database.create_agent_role_template(role, space_id)}


@router.get("/tools")
async def list_tools():
    return {"success": True, "tools": agent_teams.list_tool_capabilities()}


# --------------------------------------------------------------------------- #
# 后台非阻塞 Agent runner（Phase 2）
#
# 提交即返回 run_id，执行在后台线程推进并逐帧落库；前端可轮询
# GET /runs/{id} 或订阅 GET /runs/{id}/stream（DB 轮询式 SSE，跨 worker 安全）。
# --------------------------------------------------------------------------- #
@router.post("/runs")
async def create_run(req: AgentRunRequest, space_id: str = Depends(get_space_id)):
    requirement = (req.requirement or req.message or "").strip()
    if not requirement:
        raise APIError("requirement is required", code="INVALID_REQUEST", status_code=400)
    team_snapshot = None
    resolved_context = None
    if req.teamId:
        team_snapshot = await agent_teams.resolve_team(req.teamId, space_id)
        if not team_snapshot:
            raise APIError("team not found", code="NOT_FOUND", status_code=404)
        try:
            team_snapshot, _warnings = agent_teams.validate_team(team_snapshot)
            resolved_context = await agent_teams.resolve_input_context(req.context, space_id)
        except agent_teams.TeamValidationError as exc:
            raise APIError(str(exc), code="INVALID_TEAM_RUN", status_code=400)
        if resolved_context["kind"] not in team_snapshot["acceptedContexts"]:
            raise APIError(
                f"team does not accept {resolved_context['kind']} context",
                code="INCOMPATIBLE_CONTEXT", status_code=400)
        if team_snapshot.get("workflowType") == "development":
            raise APIError(
                "development teams must run from a software project's development workspace",
                code="DEVELOPMENT_WORKSPACE_REQUIRED", status_code=400)
    run_id = await agent_runner.submit_run(
        space_id, requirement, req.projectId, req.roles,
        team_snapshot=team_snapshot, input_context=resolved_context)
    if not run_id:
        raise APIError("提交运行失败", code="SUBMIT_FAILED", status_code=500)
    return {"success": True, "runId": run_id, "status": "running"}


@router.get("/runs")
async def list_runs(
    projectId: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    space_id: str = Depends(get_space_id),
):
    try:
        runs = await db.database.list_agent_runs(space_id, project_id=projectId, limit=limit)
        return {"success": True, "runs": runs}
    except Exception as exc:
        raise APIError(str(exc), code="LIST_RUNS_FAILED")


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    after: int = Query(0, ge=0),
    space_id: str = Depends(get_space_id),
):
    try:
        run = await db.database.get_agent_run(run_id, space_id)
        if not run:
            raise APIError("run not found", code="NOT_FOUND", status_code=404)
        events = await db.database.get_agent_run_events(run_id, space_id, after_id=after)
        pending = await db.database.list_agent_tool_approvals(run_id, space_id, status="pending")
        nodes = await db.database.list_agent_run_nodes(run_id, space_id)
        primary_output = None
        if run.get("teamSnapshot") and run.get("resultSummary"):
            output_id = run["teamSnapshot"].get("outputNodeId")
            result = run["resultSummary"].get(output_id, {})
            primary_output = result.get("structured")
            if primary_output is None:
                primary_output = result.get("text")
        return {
            "success": True,
            "run": run,
            "events": events,
            "pendingApprovals": pending,
            "nodes": nodes,
            "primaryOutput": primary_output,
            "done": run["status"] in ("completed", "failed", "cancelled"),
        }
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="GET_RUN_FAILED")


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, space_id: str = Depends(get_space_id)):
    async def event_stream():
        last_id = 0
        while True:
            run = await db.database.get_agent_run(run_id, space_id)
            if not run:
                yield sse_error("run not found")
                break
            events = await db.database.get_agent_run_events(run_id, space_id, after_id=last_id)
            for ev in events:
                last_id = ev["id"]
                payload = {"type": ev["type"], **ev["data"]}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if run["status"] in ("completed", "failed", "cancelled"):
                yield f"data: {SSE_DONE}\n\n"
                break
            await asyncio.sleep(0.6)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, space_id: str = Depends(get_space_id)):
    try:
        ok = await agent_runner.cancel_run(run_id, space_id)
        return {"success": ok, "cancelled": ok}
    except Exception as exc:
        raise APIError(str(exc), code="CANCEL_FAILED")


@router.post("/runs/{run_id}/approvals/{approval_id}")
async def decide_approval(
    run_id: str,
    approval_id: str,
    req: ApprovalDecision,
    space_id: str = Depends(get_space_id),
):
    """用户对一次工具审批做决策（允许 / 拒绝）。

    runner 线程正异步轮询该审批行，决策后自动恢复运行。
    """
    try:
        row = await db.database.get_agent_tool_approval(approval_id, run_id, space_id)
        if not row:
            raise APIError("approval not found", code="NOT_FOUND", status_code=404)
        if row["status"] != "pending":
            return {"success": False, "message": f"该审批已处理（{row['status']}）"}
        ok = await db.database.decide_agent_tool_approval(
            approval_id, run_id, space_id, approved=req.approved)
        return {"success": ok, "approvalId": approval_id, "approved": req.approved}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="DECIDE_APPROVAL_FAILED")


@router.get("/runs/{run_id}/approvals")
async def list_approvals(run_id: str, space_id: str = Depends(get_space_id)):
    """列出某运行的全部工具审批记录（含历史），供前端审批面板 / 审计使用。"""
    try:
        rows = await db.database.list_agent_tool_approvals(run_id, space_id)
        return {"success": True, "approvals": rows}
    except Exception as exc:
        raise APIError(str(exc), code="LIST_APPROVALS_FAILED")


@router.get("/runs/{run_id}/replay")
async def get_replay(run_id: str, space_id: str = Depends(get_space_id)):
    """取回某运行的可重放会话日志（逐轮模型实际看到的消息序列）。

    对应「Model-visible ⟺ logged」工程纪律：出问题可按 run_id 完整重放定位。
    """
    try:
        run = await db.database.get_agent_run(run_id, space_id)
        if not run:
            raise APIError("run not found", code="NOT_FOUND", status_code=404)
        replay = await db.database.get_agent_replay(run_id, space_id)
        return {"success": True, "replay": replay}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="GET_REPLAY_FAILED")


__all__ = ["router"]
