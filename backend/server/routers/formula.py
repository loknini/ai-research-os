"""Formula (OCR) integration routes.

``recognize`` shells out to ``scripts/formula_service.py`` (visual model);
the other endpoints operate on the local ``formula_history`` table via the
same script's CLI actions.  All requests resolve ``space_id`` and forward it to
the subprocess via the ``SPACE_ID`` environment variable so formula history
stays isolated per space.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import config
from ..deps import get_space_id
from ..helpers import run_script

router = APIRouter(prefix="/api/formula", tags=["formula"])


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
            env_extra={"SPACE_ID": space_id},
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
        "formula_service.py", "history", str(limit), fav_flag, env_extra={"SPACE_ID": space_id}
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
    result = run_script(
        "formula_service.py", "history_update", record_id, json.dumps(updates),
        env_extra={"SPACE_ID": space_id},
    )
    if result.get("notFound") is True:
        return JSONResponse(status_code=404, content={**result, "error": "NOT_FOUND"})
    if result.get("success") is False:
        return JSONResponse(status_code=500, content=result)
    return result


@router.delete("/history/{record_id}")
async def delete_history(record_id: str, space_id: str = Depends(get_space_id)):
    result = run_script(
        "formula_service.py", "history_delete", record_id, env_extra={"SPACE_ID": space_id}
    )
    if result.get("notFound") is True:
        return JSONResponse(status_code=404, content={**result, "error": "NOT_FOUND"})
    if result.get("success") is False:
        return JSONResponse(status_code=500, content=result)
    return result


@router.get("/stats")
async def stats(space_id: str = Depends(get_space_id)):
    return run_script("formula_service.py", "stats", env_extra={"SPACE_ID": space_id})


__all__ = ["router"]
