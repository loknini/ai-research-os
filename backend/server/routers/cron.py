"""Cron job routes.

Cron jobs are stored in the ``cron_jobs`` table (space-scoped).  Each handler
resolves ``space_id`` via ``Depends(get_space_id)``.  ``run`` executes the job
in a subprocess with ``SPACE_ID`` / ``DATA_DIR`` exported so the child inherits
the current space.

Phase 4 扩展：
  * ``job_type`` 字段区分任务类型（command / agent_run / arxiv_fetch）。
  * ``payload`` 字段存任务参数 JSON（agent_run 的 requirement/roles、
    arxiv_fetch 的 query/keywords/max）。
  * ``GET /api/cron/jobs/{id}/history`` 查询某任务的执行历史。
  * ``GET /api/cron/history`` 查询当前空间全部执行历史。
  * 创建/启用任务时自动初始化 ``next_run``（由调度器消费）。
"""
from __future__ import annotations

import os
import shlex
import subprocess
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import config
from .. import db
from ..cron_scheduler import compute_next_run
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
        if req.enabled:
            next_ms = compute_next_run(req.schedule, now)
            if next_ms:
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
        job = await db.database.toggle_cron_job(job_id, space_id=space_id)
        if job is None:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "NOT_FOUND", "message": "Job not found"},
            )
        # 启用时重新计算 next_run；禁用时清空
        if job["enabled"]:
            now = int(time.time() * 1000)
            next_ms = compute_next_run(job["schedule"], now)
            if next_ms:
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
        job_type = job.get("jobType") or "command"
        output = ""
        status = "success"

        if job_type == "command":
            command = job.get("command", "")
            if command:
                try:
                    env = os.environ.copy()
                    env["SPACE_ID"] = space_id
                    env["DATA_DIR"] = str(config.DATA_DIR)
                    proc = subprocess.run(
                        shlex.split(command), capture_output=True, text=True,
                        timeout=30, env=env,
                    )
                    output = (proc.stdout or "") + (proc.stderr or "")
                    status = "success" if proc.returncode == 0 else "failed"
                except Exception as exc:
                    output = f"run error: {exc}"
                    status = "error"
        elif job_type == "agent_run":
            from .. import agent_runner
            payload = job.get("payload") or {}
            requirement = payload.get("requirement") or job.get("description") or ""
            roles = payload.get("roles")
            run_id = await agent_runner.submit_run(space_id, requirement, roles=roles)
            output = f"agent run submitted: {run_id}"
        elif job_type == "arxiv_fetch":
            from scripts.fetch_arxiv import fetch_papers
            payload = job.get("payload") or {}
            end = datetime.now()
            start = end - timedelta(days=int(payload.get("days") or 1))
            papers = fetch_papers(
                search_query=payload.get("query") or "cat:cs.CV",
                keywords=payload.get("keywords") or None,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                max_results=int(payload.get("max") or 10),
            )
            output = f"fetched {len(papers)} papers"
        else:
            output = f"unknown job_type: {job_type}"
            status = "error"

        return {"success": True, "job": job, "status": status, "output": output[:2000]}
    except Exception as exc:
        raise APIError(str(exc), code="RUN_JOB_FAILED")


@router.get("/jobs/{job_id}/history")
async def job_history(job_id: str, space_id: str = Depends(get_space_id)):
    """查询某任务的执行历史。"""
    try:
        history = await db.database.get_cron_run_history(space_id=space_id, limit=50)
        filtered = [h for h in history if h.get("cron_job_id") == job_id]
        return {"success": True, "history": filtered}
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
