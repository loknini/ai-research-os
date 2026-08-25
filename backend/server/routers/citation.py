"""Citation integration routes.

Lightweight subprocess calls to ``scripts/citation_service.py``
(``search`` / ``generate`` actions).  The script prints JSON which is parsed
and forwarded.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..helpers import run_script

router = APIRouter(prefix="/api/citation", tags=["citation"])


@router.get("/search")
async def search(q: str = ""):
    if not q or not q.strip():
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "INVALID_QUERY", "message": "q is required"},
        )
    return run_script("citation_service.py", "search", q)


class CitationGenerate(BaseModel):
    paper: Dict[str, Any]


@router.post("/generate")
async def generate(req: CitationGenerate):
    return run_script("citation_service.py", "generate", json.dumps(req.paper))


__all__ = ["router"]
