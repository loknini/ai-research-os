"""Task Hub CRUD routes -> in-process ``scripts/database.py``.

Every handler resolves ``space_id`` via ``Depends(get_space_id)`` and passes it
through to the DB layer for soft isolation.
"""
from __future__ import annotations

import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import db
from ..deps import get_space_id
from ..errors import APIError

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    status: str = "todo"
    priority: str = "medium"
    deadline: Optional[int] = None
    tags: List[str] = []
    projectId: Optional[str] = None
    parentTaskId: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    deadline: Optional[int] = None
    tags: Optional[List[str]] = None
    projectId: Optional[str] = None
    parentTaskId: Optional[str] = None
    completedAt: Optional[int] = None


@router.get("")
async def list_tasks(
    space_id: str = Depends(get_space_id),
    projectId: Optional[str] = None,
    status: Optional[str] = None,
):
    try:
        tasks = await db.database.get_all_tasks(space_id=space_id, project_id=projectId, status=status)
        return {"success": True, "tasks": tasks}
    except Exception as exc:
        raise APIError(str(exc), code="LIST_TASKS_FAILED")


@router.post("")
async def create_task(req: TaskCreate, space_id: str = Depends(get_space_id)):
    try:
        now = int(time.time() * 1000)
        task = {
            "id": str(uuid.uuid4()),
            "title": req.title,
            "description": req.description,
            "status": req.status,
            "priority": req.priority,
            "deadline": req.deadline,
            "tags": req.tags,
            "projectId": req.projectId,
            "parentTaskId": req.parentTaskId,
            "createdAt": now,
            "updatedAt": now,
        }
        if not await db.database.insert_task(task, space_id=space_id):
            raise APIError("插入任务失败", code="INSERT_FAILED")
        return {"success": True, "task": task}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="CREATE_TASK_FAILED")


@router.put("/{task_id}")
async def update_task(task_id: str, req: TaskUpdate, space_id: str = Depends(get_space_id)):
    try:
        updates = {k: v for k, v in req.model_dump(exclude_none=True).items()}
        if not await db.database.update_task(task_id, updates, space_id=space_id):
            raise APIError("更新任务失败", code="UPDATE_FAILED")
        return {"success": True, "task": await db.database.get_task_by_id(task_id, space_id=space_id)}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="UPDATE_TASK_FAILED")


@router.delete("/{task_id}")
async def delete_task(task_id: str, space_id: str = Depends(get_space_id)):
    try:
        ok = await db.database.delete_task(task_id, space_id=space_id)
        return {"success": ok, "deleted": ok}
    except Exception as exc:
        raise APIError(str(exc), code="DELETE_TASK_FAILED")


__all__ = ["router"]
