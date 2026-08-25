"""Software Hub (projects) CRUD routes -> in-process ``scripts/database.py``.

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

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    ideaDescription: str = ""
    techStack: List[str] = []
    status: str = "design"
    localPath: Optional[str] = None
    githubUrl: Optional[str] = None
    architecture: Dict[str, Any] = {}
    features: List[Any] = []
    milestones: List[Any] = []
    aiGeneratedCode: bool = False


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    ideaDescription: Optional[str] = None
    techStack: Optional[List[str]] = None
    status: Optional[str] = None
    localPath: Optional[str] = None
    githubUrl: Optional[str] = None
    architecture: Optional[Dict[str, Any]] = None
    features: Optional[List[Any]] = None
    milestones: Optional[List[Any]] = None
    aiGeneratedCode: Optional[bool] = None


@router.get("")
async def list_projects(space_id: str = Depends(get_space_id), status: Optional[str] = None):
    try:
        projects = await db.database.get_all_projects(space_id=space_id, status=status)
        return {"success": True, "projects": projects}
    except Exception as exc:
        raise APIError(str(exc), code="LIST_PROJECTS_FAILED")


@router.post("")
async def create_project(req: ProjectCreate, space_id: str = Depends(get_space_id)):
    try:
        now = int(time.time() * 1000)
        project = {
            "id": str(uuid.uuid4()),
            "name": req.name,
            "description": req.description,
            "ideaDescription": req.ideaDescription,
            "techStack": req.techStack,
            "status": req.status,
            "localPath": req.localPath,
            "githubUrl": req.githubUrl,
            "architecture": req.architecture,
            "features": req.features,
            "milestones": req.milestones,
            "aiGeneratedCode": req.aiGeneratedCode,
            "createdAt": now,
            "updatedAt": now,
        }
        if not await db.database.insert_project(project, space_id=space_id):
            raise APIError("插入项目失败", code="INSERT_FAILED")
        return {"success": True, "project": project}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="CREATE_PROJECT_FAILED")


@router.get("/{project_id}")
async def get_project(project_id: str, space_id: str = Depends(get_space_id)):
    try:
        project = await db.database.get_project_by_id(project_id, space_id=space_id)
        if not project:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "NOT_FOUND", "message": "Project not found"},
            )
        return {"success": True, "project": project}
    except Exception as exc:
        raise APIError(str(exc), code="GET_PROJECT_FAILED")


@router.put("/{project_id}")
async def update_project(project_id: str, req: ProjectUpdate, space_id: str = Depends(get_space_id)):
    try:
        updates = {k: v for k, v in req.model_dump(exclude_none=True).items()}
        if not await db.database.update_project(project_id, updates, space_id=space_id):
            raise APIError("更新项目失败", code="UPDATE_FAILED")
        return {"success": True, "project": await db.database.get_project_by_id(project_id, space_id=space_id)}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="UPDATE_PROJECT_FAILED")


@router.delete("/{project_id}")
async def delete_project(project_id: str, space_id: str = Depends(get_space_id)):
    try:
        ok = await db.database.delete_project(project_id, space_id=space_id)
        return {"success": ok, "deleted": ok}
    except Exception as exc:
        raise APIError(str(exc), code="DELETE_PROJECT_FAILED")


@router.get("/{project_id}/tasks")
async def project_tasks(project_id: str, space_id: str = Depends(get_space_id)):
    try:
        tasks = await db.database.get_tasks_by_project(project_id, space_id=space_id)
        return {"success": True, "tasks": tasks}
    except Exception as exc:
        raise APIError(str(exc), code="PROJECT_TASKS_FAILED")


__all__ = ["router"]
