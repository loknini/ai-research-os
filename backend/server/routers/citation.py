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


class CitationResolve(BaseModel):
    title: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None


@router.post("/resolve")
async def resolve(req: CitationResolve):
    """三段式论文元数据解析：DOI (Crossref) → arXiv → 标题关键词 (Crossref)。
    用 JSON payload 传参以避免 sys.argv 拆空格。"""
    payload = json.dumps(
        {
            "doi": req.doi,
            "arxiv_id": req.arxiv_id,
            "title": req.title,
        },
        ensure_ascii=False,
    )
    return run_script("citation_service.py", "resolve", payload)


@router.post("/generate")
async def generate(req: CitationGenerate):
    return run_script("citation_service.py", "generate", json.dumps(req.paper))


__all__ = ["router"]
