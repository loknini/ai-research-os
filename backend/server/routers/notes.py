"""Knowledge Hub (notes) CRUD routes -> in-process ``scripts/database.py``.

Every handler resolves ``space_id`` via ``Depends(get_space_id)`` and passes it
through to the DB layer for soft isolation.  ``update_note`` in the DB layer
auto-creates a version snapshot (also space-scoped).
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

router = APIRouter(prefix="/api/notes", tags=["notes"])


class NoteCreate(BaseModel):
    title: str
    content: str = ""
    summary: Optional[str] = None
    type: str = "note"
    tags: List[str] = []
    paperId: Optional[str] = None
    projectId: Optional[str] = None
    parentNoteId: Optional[str] = None
    isFavorite: bool = False
    aiGenerated: bool = False


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    type: Optional[str] = None
    tags: Optional[List[str]] = None
    paperId: Optional[str] = None
    projectId: Optional[str] = None
    parentNoteId: Optional[str] = None
    isFavorite: Optional[bool] = None
    aiGenerated: Optional[bool] = None


@router.get("")
async def list_notes(
    space_id: str = Depends(get_space_id),
    noteType: Optional[str] = None,
    paperId: Optional[str] = None,
    projectId: Optional[str] = None,
):
    try:
        notes = await db.database.get_all_notes(
            space_id=space_id, note_type=noteType, paper_id=paperId, project_id=projectId
        )
        return {"success": True, "notes": notes}
    except Exception as exc:
        raise APIError(str(exc), code="LIST_NOTES_FAILED")


@router.post("")
async def create_note(req: NoteCreate, space_id: str = Depends(get_space_id)):
    try:
        now = int(time.time() * 1000)
        note = {
            "id": str(uuid.uuid4()),
            "title": req.title,
            "content": req.content,
            "summary": req.summary,
            "type": req.type,
            "tags": req.tags,
            "paperId": req.paperId,
            "projectId": req.projectId,
            "parentNoteId": req.parentNoteId,
            "isFavorite": req.isFavorite,
            "aiGenerated": req.aiGenerated,
            "createdAt": now,
            "updatedAt": now,
        }
        if not await db.database.insert_note(note, space_id=space_id):
            raise APIError("插入笔记失败", code="INSERT_FAILED")
        return {"success": True, "note": note}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="CREATE_NOTE_FAILED")


@router.get("/{note_id}")
async def get_note(note_id: str, space_id: str = Depends(get_space_id)):
    try:
        note = await db.database.get_note_by_id(note_id, space_id=space_id)
        if not note:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "NOT_FOUND", "message": "Note not found"},
            )
        return {"success": True, "note": note}
    except Exception as exc:
        raise APIError(str(exc), code="GET_NOTE_FAILED")


@router.put("/{note_id}")
async def update_note(note_id: str, req: NoteUpdate, space_id: str = Depends(get_space_id)):
    try:
        updates = {k: v for k, v in req.model_dump(exclude_none=True).items()}
        if not await db.database.update_note(note_id, updates, space_id=space_id):
            raise APIError("更新笔记失败", code="UPDATE_FAILED")
        return {"success": True, "note": await db.database.get_note_by_id(note_id, space_id=space_id)}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="UPDATE_NOTE_FAILED")


@router.delete("/{note_id}")
async def delete_note(note_id: str, space_id: str = Depends(get_space_id)):
    try:
        ok = await db.database.delete_note(note_id, space_id=space_id)
        return {"success": ok, "deleted": ok}
    except Exception as exc:
        raise APIError(str(exc), code="DELETE_NOTE_FAILED")


__all__ = ["router"]
