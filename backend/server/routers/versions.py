"""Version history routes -> in-process ``scripts/database.py``.

Every handler resolves ``space_id`` via ``Depends(get_space_id)`` so version
snapshots stay scoped to the owning space.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import db
from ..deps import get_space_id
from ..errors import APIError

router = APIRouter(prefix="/api/versions", tags=["versions"])


class CompareRequest(BaseModel):
    versionId1: str
    versionId2: str


class RestoreRequest(BaseModel):
    versionId: str


@router.get("/detail/{version_id}")
async def version_detail(version_id: str, space_id: str = Depends(get_space_id)):
    try:
        version = await db.database.get_version_by_id(version_id, space_id=space_id)
        if not version:
            return {"success": False, "error": "NOT_FOUND", "message": "Version not found"}
        return {"success": True, "version": version}
    except Exception as exc:
        raise APIError(str(exc), code="GET_VERSION_FAILED")


@router.get("/{entity_type}/{entity_id}")
async def list_versions(
    entity_type: str,
    entity_id: str,
    space_id: str = Depends(get_space_id),
    limit: int = 50,
):
    try:
        versions = await db.database.get_versions(entity_type, entity_id, limit=limit, space_id=space_id)
        return {"success": True, "versions": versions}
    except Exception as exc:
        raise APIError(str(exc), code="LIST_VERSIONS_FAILED")


@router.post("/compare")
async def compare(req: CompareRequest, space_id: str = Depends(get_space_id)):
    try:
        result = await db.database.compare_versions(req.versionId1, req.versionId2, space_id=space_id)
        if "error" in result:
            return {"success": False, "error": "COMPARE_FAILED", "message": result["error"]}
        return {"success": True, **result}
    except Exception as exc:
        raise APIError(str(exc), code="COMPARE_FAILED")


@router.post("/restore")
async def restore(req: RestoreRequest, space_id: str = Depends(get_space_id)):
    try:
        data = await db.database.restore_version(req.versionId, space_id=space_id)
        if data is None:
            return {"success": False, "error": "NOT_FOUND", "message": "Version not found"}
        return {"success": True, "data": data}
    except Exception as exc:
        raise APIError(str(exc), code="RESTORE_FAILED")


__all__ = ["router"]
