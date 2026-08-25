"""Experiment Hub CRUD routes -> in-process ``scripts/database.py``.

Every handler resolves ``space_id`` via ``Depends(get_space_id)`` and passes it
through to the DB layer for soft isolation.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import db
from ..deps import get_space_id
from ..errors import APIError

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


class ExperimentCreate(BaseModel):
    name: str
    description: str = ""
    projectId: Optional[str] = None
    status: str = "planning"
    config: Dict[str, Any] = {}
    tags: List[str] = []
    swanlabProject: Optional[str] = None
    swanlabExperimentId: Optional[str] = None
    totalRuns: int = 0


class ExperimentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    projectId: Optional[str] = None
    status: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    swanlabProject: Optional[str] = None
    swanlabExperimentId: Optional[str] = None
    totalRuns: Optional[int] = None
    bestMetricName: Optional[str] = None
    bestMetricValue: Optional[Any] = None


@router.get("")
async def list_experiments(
    space_id: str = Depends(get_space_id),
    status: Optional[str] = None,
    projectId: Optional[str] = None,
):
    try:
        experiments = await db.database.get_all_experiments(space_id=space_id, status=status, project_id=projectId)
        return {"success": True, "experiments": experiments}
    except Exception as exc:
        raise APIError(str(exc), code="LIST_EXPERIMENTS_FAILED")


@router.post("")
async def create_experiment(req: ExperimentCreate, space_id: str = Depends(get_space_id)):
    try:
        now = int(time.time() * 1000)
        experiment = {
            "id": str(uuid.uuid4()),
            "name": req.name,
            "description": req.description,
            "projectId": req.projectId,
            "status": req.status,
            "config": req.config,
            "tags": req.tags,
            "swanlabProject": req.swanlabProject,
            "swanlabExperimentId": req.swanlabExperimentId,
            "totalRuns": req.totalRuns,
            "createdAt": now,
            "updatedAt": now,
        }
        if not await db.database.insert_experiment(experiment, space_id=space_id):
            raise APIError("插入实验失败", code="INSERT_FAILED")
        return {"success": True, "experiment": experiment}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="CREATE_EXPERIMENT_FAILED")


@router.get("/{experiment_id}")
async def get_experiment(experiment_id: str, space_id: str = Depends(get_space_id)):
    try:
        experiment = await db.database.get_experiment_by_id(experiment_id, space_id=space_id)
        if not experiment:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "NOT_FOUND", "message": "Experiment not found"},
            )
        return {"success": True, "experiment": experiment}
    except Exception as exc:
        raise APIError(str(exc), code="GET_EXPERIMENT_FAILED")


@router.put("/{experiment_id}")
async def update_experiment(experiment_id: str, req: ExperimentUpdate, space_id: str = Depends(get_space_id)):
    try:
        updates = {k: v for k, v in req.model_dump(exclude_none=True).items()}
        if not await db.database.update_experiment(experiment_id, updates, space_id=space_id):
            raise APIError("更新实验失败", code="UPDATE_FAILED")
        return {"success": True, "experiment": await db.database.get_experiment_by_id(experiment_id, space_id=space_id)}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="UPDATE_EXPERIMENT_FAILED")


@router.delete("/{experiment_id}")
async def delete_experiment(experiment_id: str, space_id: str = Depends(get_space_id)):
    try:
        ok = await db.database.delete_experiment(experiment_id, space_id=space_id)
        return {"success": ok, "deleted": ok}
    except Exception as exc:
        raise APIError(str(exc), code="DELETE_EXPERIMENT_FAILED")


@router.get("/{experiment_id}/runs")
async def experiment_runs(experiment_id: str, space_id: str = Depends(get_space_id)):
    try:
        runs = await db.database.get_experiment_runs(experiment_id, space_id=space_id)
        return {"success": True, "runs": runs}
    except Exception as exc:
        raise APIError(str(exc), code="EXPERIMENT_RUNS_FAILED")


__all__ = ["router"]
