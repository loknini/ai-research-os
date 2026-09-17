"""Formula (OCR) integration routes.

``recognize`` shells out to ``scripts/formula_service.py`` (visual model).
History reads/stats retain the compatible CLI path; writes use the shared
async database layer directly, avoiding a subprocess/SQLite lock inversion.
All operations remain isolated by ``space_id``.
"""
from __future__ import annotations

import base64
import os
import tempfile
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import config, db
from ..deps import get_space_id
from ..helpers import run_script

router = APIRouter(prefix="/api/formula", tags=["formula"])


def _script_env(space_id: str) -> dict[str, str]:
    """Child-process context; app lifespan has already initialized the DB."""
    return {"SPACE_ID": space_id, "AIROS_DB_ALREADY_INITIALIZED": "1"}


class RecognizeRequest(BaseModel):
    imagePath: Optional[str] = None
    imageBase64: Optional[str] = None
    useTurbo: bool = False
    token: Optional[str] = None


class HistoryUpdate(BaseModel):
    id: Optional[str] = None
    recordId: Optional[str] = None
    updates: Optional[dict] = None
    isFavorite: Optional[bool] = None
    is_favorite: Optional[bool] = None
    tags: Optional[List[str]] = None
    note: Optional[str] = None


@router.post("/recognize")
async def recognize(req: RecognizeRequest, space_id: str = Depends(get_space_id)):
    image_path: Optional[str] = None
    tmp_path: Optional[str] = None
    try:
        if req.imageBase64:
            b64 = req.imageBase64
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            raw = base64.b64decode(b64)
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".png", dir=str(config.DATA_DIR)
            )
            tmp.write(raw)
            tmp.close()
            tmp_path = tmp.name
            image_path = tmp_path
        elif req.imagePath:
            image_path = req.imagePath
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "INVALID_REQUEST",
                    "message": "imagePath or imageBase64 required",
                },
            )
        turbo_flag = "true" if req.useTurbo else "false"
        return run_script(
            "formula_service.py", "test", image_path, req.token or "", turbo_flag,
            env_extra=_script_env(space_id),
        )
    except Exception as exc:
        return {"success": False, "error": "RECOGNIZE_FAILED", "message": str(exc)}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@router.get("/history")
async def history(favorites: bool = False, limit: int = 100, space_id: str = Depends(get_space_id)):
    fav_flag = "true" if favorites else "false"
    return run_script(
        "formula_service.py", "history", str(limit), fav_flag,
        env_extra=_script_env(space_id)
    )


@router.put("/history")
async def update_history(req: HistoryUpdate, space_id: str = Depends(get_space_id)):
    record_id = req.id or req.recordId
    if not record_id:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "INVALID_REQUEST", "message": "id is required"},
        )
    updates = dict(req.updates or {})
    flat = req.model_dump(
        exclude_none=True,
        exclude={"id", "recordId", "updates"},
    )
    updates.update(flat)
    supported = {"latexCode", "latex_code", "isFavorite", "is_favorite", "tags", "note"}
    if not any(key in supported for key in updates):
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "INVALID_REQUEST",
                "message": "at least one supported update field is required",
            },
        )
    try:
        updated = await db.database.update_formula_history_record(
            record_id, updates, space_id)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"success": False, "updated": False, "error": str(exc)},
        )
    if not updated:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "updated": False,
                "notFound": True,
                "error": "NOT_FOUND",
            },
        )
    return {"success": True, "updated": True}


@router.delete("/history/{record_id}")
async def delete_history(record_id: str, space_id: str = Depends(get_space_id)):
    try:
        deleted = await db.database.delete_formula_history_record(
            record_id, space_id)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"success": False, "deleted": False, "error": str(exc)},
        )
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "deleted": False,
                "notFound": True,
                "error": "NOT_FOUND",
            },
        )
    return {"success": True, "deleted": True}


@router.get("/stats")
async def stats(space_id: str = Depends(get_space_id)):
    return run_script(
        "formula_service.py", "stats", env_extra=_script_env(space_id))


__all__ = ["router"]
