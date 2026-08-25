"""Global search route -> in-process ``scripts/database.py`` (global_search).

Scoped to the caller's ``space_id`` so cross-space results never leak.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import db
from ..deps import get_space_id
from ..errors import APIError

router = APIRouter(prefix="/api", tags=["search"])

_EMPTY = {
    "papers": [],
    "tasks": [],
    "projects": [],
    "notes": [],
    "experiments": [],
}


@router.get("/search")
async def global_search(q: str = "", limit: int = 50, space_id: str = Depends(get_space_id)):
    try:
        if not q or not q.strip():
            return {"success": True, **_EMPTY}
        results = await db.database.global_search(q, space_id=space_id, limit=limit)
        return {"success": True, **results}
    except Exception as exc:
        raise APIError(str(exc), code="SEARCH_FAILED")


__all__ = ["router"]
