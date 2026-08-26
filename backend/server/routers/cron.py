"""Cron job routes.

Cron jobs are stored in the ``cron_jobs`` table (space-scoped).  Each handler
resolves ``space_id`` via ``Depends(get_space_id)``. Manual and scheduled runs
share the same command / Agent / arXiv dispatcher and history writer; command
children inherit ``SPACE_ID`` / ``DATA_DIR``.

Phase 4 扩展：
  * ``job_type`` 字段区分任务类型（command / agent_run / arxiv_fetch）。
  * ``payload`` 字段存任务参数 JSON（agent_run 的 requirement/roles、
    arxiv_fetch 的 query/keywords/max）。
  * ``GET /api/cron/jobs/{id}/history`` 查询某任务的执行历史。
  * ``GET /api/cron/history`` 查询当前空间全部执行历史。
  * 创建/启用任务时自动初始化 ``next_run``（由调度器消费）。
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import db
from ..cron_scheduler import compute_next_run, dispatch_job
from ..deps import get_space_id
from ..errors import APIError

router = APIRouter(prefix="/api/cron", tags=["cron"])


class JobCreate(BaseModel):
    name: str
    description: str = ""
    schedule: str
    command: str = ""
    jobType: str = "command"
    payload: Optional[dict] = None
    enabled: bool = True


@router.get("/jobs")
async def list_jobs(space_id: str = Depends(get_space_id)):
    try:
        jobs = await db.database.get_cron_jobs(space_id=space_id)
        return {"success": True, "jobs": jobs}
    except Exception as exc:
        raise APIError(str(exc), code="LIST_JOBS_FAILED")


@router.post("/jobs")
async def create_job(req: JobCreate, space_id: str = Depends(get_space_id)):
    try:
        now = int(time.time() * 1000)
        if req.jobType not in {"command", "agent_run", "arxiv_fetch"}:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "INVALID_JOB_TYPE", "message": "Unsupported jobType"},
            )
        next_ms = compute_next_run(req.schedule, now)
        if next_ms is None:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "INVALID_SCHEDULE", "message": "Invalid cron schedule"},
            )
        job = {
            "id": str(uuid.uuid4()),
            "name": req.name,
            "description": req.description,
            "schedule": req.schedule,
            "command": req.command,
            "jobType": req.jobType,
            "payload": req.payload,
            "enabled": req.enabled,
            "createdAt": now,
        }
        created = await db.database.create_cron_job(job, space_id=space_id)
        if not created:
            raise APIError("创建定时任务失败", code="CREATE_JOB_FAILED")
        # 启用时初始化 next_run（调度器消费）
        if req.enabled and next_ms is not None:
            await db.database.init_cron_next_run(created["id"], next_ms)
            created["nextRun"] = next_ms
        return {"success": True, "job": created}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="CREATE_JOB_FAILED")


@router.post("/jobs/{job_id}/toggle")
async def toggle_job(job_id: str, space_id: str = Depends(get_space_id)):
    try:
        current = next(
            (item for item in await db.database.get_cron_jobs(space_id=space_id) if item["id"] == job_id),
            None,
        )
        if current is None:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "NOT_FOUND", "message": "Job not found"},
            )

        next_ms: Optional[int] = None
        if not current["enabled"]:
            next_ms = compute_next_run(current["schedule"], int(time.time() * 1000))
            if next_ms is None:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "INVALID_SCHEDULE", "message": "Invalid cron schedule"},
                )

        job = await db.database.toggle_cron_job(job_id, space_id=space_id)
        if job is None:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "NOT_FOUND", "message": "Job not found"},
            )
        # 启用时重新计算 next_run；禁用时清空
        if job["enabled"]:
            await db.database.init_cron_next_run(job_id, next_ms)
            job["nextRun"] = next_ms
        else:
            await db.database.init_cron_next_run(job_id, 0)
            job["nextRun"] = None
        return {"success": True, "job": job}
    except Exception as exc:
        raise APIError(str(exc), code="TOGGLE_JOB_FAILED")


@router.post("/jobs/{job_id}/run")
async def run_job(job_id: str, space_id: str = Depends(get_space_id)):
    """手动立即运行某任务（不影响调度器的 next_run 计算）。"""
    try:
        job = await db.database.run_cron_job(job_id, space_id=space_id)
        if job is None:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "NOT_FOUND", "message": "Job not found"},
            )
        status, output = await dispatch_job(job, space_id=space_id)

        return {"success": True, "job": job, "status": status, "output": output[:2000]}
    except Exception as exc:
        raise APIError(str(exc), code="RUN_JOB_FAILED")


@router.get("/jobs/{job_id}/history")
async def job_history(job_id: str, space_id: str = Depends(get_space_id)):
    """查询某任务的执行历史。"""
    try:
        history = await db.database.get_cron_run_history(
            space_id=space_id,
            cron_job_id=job_id,
            limit=50,
        )
        return {"success": True, "history": history}
    except Exception as exc:
        raise APIError(str(exc), code="HISTORY_FAILED")


@router.get("/history")
async def all_history(space_id: str = Depends(get_space_id)):
    """查询当前空间全部定时任务执行历史。"""
    try:
        history = await db.database.get_cron_run_history(space_id=space_id, limit=50)
        return {"success": True, "history": history}
    except Exception as exc:
        raise APIError(str(exc), code="HISTORY_FAILED")


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, space_id: str = Depends(get_space_id)):
    try:
        ok = await db.database.delete_cron_job(job_id, space_id=space_id)
        if not ok:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "NOT_FOUND", "message": "Job not found"},
            )
        return {"success": True, "deleted": True}
    except Exception as exc:
        raise APIError(str(exc), code="DELETE_JOB_FAILED")


__all__ = ["router"]
