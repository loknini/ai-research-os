"""Autonomous software-development workspace API."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import agent_teams, db, development_runner
from ..deps import get_space_id
from ..development_workspace import WorkspaceError, apply_workspace, validate_project, workspace_diff
from ..errors import APIError, SSE_DONE, sse_error

router = APIRouter(tags=["development"])


class WorkspaceValidateRequest(BaseModel):
    localPath: Optional[str] = None


class DevelopmentConfigRequest(BaseModel):
    runtime: List[str] = Field(default_factory=list)
    packageManager: Optional[str] = None
    testCommands: List[List[str]] = Field(default_factory=list)
    buildCommands: List[List[str]] = Field(default_factory=list)
    ignorePaths: List[str] = Field(default_factory=list)


class DevelopmentRunRequest(BaseModel):
    goal: str
    teamId: str = "builtin-software-development"
    successCriteria: List[str] = Field(default_factory=list)
    maxIterations: int = Field(default=12, ge=1, le=50)
    maxDurationMinutes: int = Field(default=60, ge=5, le=480)
    authorization: Dict[str, Any] = Field(
        default_factory=lambda: {"workspaceWrites": True, "verificationCommands": True})


class DevelopmentContinueRequest(BaseModel):
    additionalIterations: int = Field(default=4, ge=1, le=50)
    additionalMinutes: int = Field(default=30, ge=5, le=480)
    feedback: Optional[str] = Field(default=None, max_length=20000)


class DevelopmentApplyRequest(BaseModel):
    baseRevision: str
    diffDigest: str


async def _project(project_id: str, space_id: str) -> Dict[str, Any]:
    project = await db.database.get_project_by_id(project_id, space_id)
    if not project:
        raise APIError("project not found", code="NOT_FOUND", status_code=404)
    return project


async def _run(run_id: str, space_id: str) -> Dict[str, Any]:
    run = await db.database.get_agent_run(run_id, space_id)
    if not run or run.get("runKind") != "development":
        raise APIError("development run not found", code="NOT_FOUND", status_code=404)
    return run


@router.post("/api/projects/{project_id}/workspace/validate")
async def validate_workspace(project_id: str, req: WorkspaceValidateRequest,
                             space_id: str = Depends(get_space_id)):
    project = await _project(project_id, space_id)
    if req.localPath is not None:
        project = {**project, "localPath": req.localPath}
    try:
        return {"success": True, "workspace": await asyncio.to_thread(validate_project, project)}
    except WorkspaceError as exc:
        raise APIError(str(exc), code="INVALID_WORKSPACE", status_code=400)


@router.put("/api/projects/{project_id}/development-config")
async def update_development_config(project_id: str, req: DevelopmentConfigRequest,
                                    space_id: str = Depends(get_space_id)):
    await _project(project_id, space_id)
    config = req.model_dump()
    if len(config["ignorePaths"]) > 100 or any(
        not value or value.startswith(("/", "\\")) or ".." in value.replace("\\", "/").split("/")
        for value in config["ignorePaths"]
    ):
        raise APIError("ignorePaths must contain safe relative paths", code="INVALID_REQUEST",
                       status_code=400)
    if not await db.database.update_project(project_id, {"developmentConfig": config}, space_id):
        raise APIError("development config update failed", code="UPDATE_FAILED")
    return {"success": True, "developmentConfig": config}


@router.post("/api/projects/{project_id}/development-runs")
async def create_development_run(project_id: str, req: DevelopmentRunRequest,
                                 space_id: str = Depends(get_space_id)):
    goal = req.goal.strip()
    if not goal:
        raise APIError("goal is required", code="INVALID_REQUEST", status_code=400)
    if len(req.successCriteria) > 20 or any(len(item) > 2000 for item in req.successCriteria):
        raise APIError("successCriteria accepts at most 20 short items", code="INVALID_REQUEST",
                       status_code=400)
    project = await _project(project_id, space_id)
    team = await agent_teams.resolve_team(req.teamId, space_id)
    if not team:
        raise APIError("team not found", code="NOT_FOUND", status_code=404)
    try:
        team, warnings = agent_teams.validate_team(team)
    except agent_teams.TeamValidationError as exc:
        raise APIError(str(exc), code="INVALID_TEAM", status_code=400)
    if team.get("workflowType") != "development" or "software_project" not in team["acceptedContexts"]:
        raise APIError("team is not a software development team", code="INCOMPATIBLE_CONTEXT",
                       status_code=400)
    authorization = {
        "workspaceWrites": req.authorization.get("workspaceWrites") is True,
        "verificationCommands": req.authorization.get("verificationCommands") is True,
        "network": False, "dependencyInstall": False, "destructive": False,
    }
    if not authorization["workspaceWrites"] or not authorization["verificationCommands"]:
        raise APIError("workspace writes and verification commands must be authorized",
                       code="AUTHORIZATION_REQUIRED", status_code=400)
    run_id = await development_runner.submit(
        space_id, project, goal, team, req.successCriteria,
        req.maxIterations, req.maxDurationMinutes, authorization)
    if not run_id:
        raise APIError("development run submission failed", code="SUBMIT_FAILED")
    await db.database.update_project(project_id, {"status": "developing"}, space_id)
    return {"success": True, "runId": run_id, "status": "pending", "warnings": warnings}


@router.get("/api/projects/{project_id}/development-runs")
async def list_project_development_runs(project_id: str,
                                        limit: int = Query(50, ge=1, le=200),
                                        space_id: str = Depends(get_space_id)):
    await _project(project_id, space_id)
    runs = await db.database.list_agent_runs(space_id, project_id=project_id, limit=limit)
    return {"success": True, "runs": [run for run in runs if run.get("runKind") == "development"]}


async def _detail(run: Dict[str, Any], space_id: str) -> Dict[str, Any]:
    steps, artifacts, approvals = await asyncio.gather(
        db.database.list_development_steps(run["id"], space_id),
        db.database.list_development_artifacts(run["id"], space_id),
        db.database.list_agent_tool_approvals(run["id"], space_id, status="pending"),
    )
    diff_summary = None
    if run.get("workspaceSnapshot") and run.get("phase") in {"awaiting_apply", "applied", "conflict"}:
        try:
            value = await asyncio.to_thread(workspace_diff, run["workspaceSnapshot"])
            diff_summary = {key: item for key, item in value.items() if key != "patch"}
        except WorkspaceError:
            pass
    return {"success": True, "run": run, "steps": steps, "artifacts": artifacts,
            "pendingApprovals": approvals, "diff": diff_summary,
            "done": run["status"] in {"completed", "failed", "cancelled"}}


@router.get("/api/development/runs/{run_id}")
async def get_development_run(run_id: str, space_id: str = Depends(get_space_id)):
    return await _detail(await _run(run_id, space_id), space_id)


@router.get("/api/development/runs/{run_id}/stream")
async def stream_development_run(run_id: str, space_id: str = Depends(get_space_id)):
    await _run(run_id, space_id)
    async def event_stream():
        last_id = 0
        while True:
            run = await db.database.get_agent_run(run_id, space_id)
            if not run or run.get("runKind") != "development":
                yield sse_error("development run not found")
                break
            events = await db.database.get_agent_run_events(run_id, space_id, after_id=last_id)
            for event in events:
                last_id = event["id"]
                yield f"data: {json.dumps({'type': event['type'], **event['data']}, ensure_ascii=False)}\n\n"
            if run["status"] in {"completed", "failed", "cancelled"}:
                yield f"data: {SSE_DONE}\n\n"
                break
            await asyncio.sleep(0.6)
    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/development/runs/{run_id}/cancel")
async def cancel_development_run(run_id: str, space_id: str = Depends(get_space_id)):
    await _run(run_id, space_id)
    ok = await db.database.cancel_agent_run(run_id, space_id)
    if ok:
        development_runner.cancel(run_id)
    return {"success": ok, "cancelled": ok}


@router.post("/api/development/runs/{run_id}/continue")
async def continue_development_run(run_id: str, req: DevelopmentContinueRequest,
                                   space_id: str = Depends(get_space_id)):
    await _run(run_id, space_id)
    ok = await db.database.continue_development_run(
        run_id, space_id, req.additionalIterations, req.additionalMinutes, req.feedback)
    if not ok:
        raise APIError("only a budget-exhausted run can be continued", code="INVALID_STATE",
                       status_code=409)
    development_runner.spawn(run_id, space_id)
    return {"success": True, "status": "pending"}


@router.get("/api/development/runs/{run_id}/diff")
async def get_development_diff(run_id: str, space_id: str = Depends(get_space_id)):
    run = await _run(run_id, space_id)
    if not run.get("workspaceSnapshot"):
        raise APIError("workspace is not prepared", code="INVALID_STATE", status_code=409)
    try:
        return {"success": True, **await asyncio.to_thread(workspace_diff, run["workspaceSnapshot"])}
    except WorkspaceError as exc:
        raise APIError(str(exc), code="DIFF_FAILED", status_code=409)


@router.get("/api/development/runs/{run_id}/artifacts")
async def get_development_artifacts(run_id: str, space_id: str = Depends(get_space_id)):
    await _run(run_id, space_id)
    return {"success": True,
            "artifacts": await db.database.list_development_artifacts(run_id, space_id)}


@router.post("/api/development/runs/{run_id}/apply")
async def apply_development_run(run_id: str, req: DevelopmentApplyRequest,
                                space_id: str = Depends(get_space_id)):
    run = await _run(run_id, space_id)
    if run["status"] != "completed" or run.get("phase") not in {"awaiting_apply", "conflict"}:
        raise APIError("run is not ready to apply", code="INVALID_STATE", status_code=409)
    try:
        result = await asyncio.to_thread(
            apply_workspace, run["workspaceSnapshot"], req.baseRevision, req.diffDigest)
    except WorkspaceError as exc:
        await db.database.update_agent_run(run_id, space_id, phase="conflict", error_message=str(exc))
        raise APIError(str(exc), code="APPLY_CONFLICT", status_code=409)
    await db.database.update_agent_run(run_id, space_id, phase="applied", error_message="")
    await db.database.add_agent_run_event(
        run_id, space_id, {"type": "development_applied", "phase": "applied", **result})
    return {"success": True, **result}


__all__ = ["router"]
