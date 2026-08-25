"""Paper Hub routes.

CRUD + arXiv fetch/download are in-process ``scripts/database.py`` /
``scripts/fetch_arxiv.py`` calls.  The AI summary uses the configurable
``llm.py`` client and degrades to ``summarize_paper.generate_fallback_summary``
when the LLM is unavailable.

All data handlers resolve ``space_id`` via ``Depends(get_space_id)`` and pass it
through to the DB layer for soft isolation.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import config, db
from ..deps import get_space_id
from ..errors import APIError
from ..llm import llm_client
from ..schemas import FetchPapersRequest

router = APIRouter(prefix="/api/papers", tags=["papers"])


@router.get("")
async def list_papers(
    space_id: str = Depends(get_space_id),
    limit: int = 100,
    offset: int = 0,
):
    try:
        papers = await db.database.get_all_papers(space_id=space_id, limit=limit, offset=offset)
        return {"success": True, "papers": papers}
    except Exception as exc:
        raise APIError(str(exc), code="LIST_PAPERS_FAILED")


@router.post("/fetch")
async def fetch_papers(req: FetchPapersRequest, space_id: str = Depends(get_space_id)):
    try:
        from scripts import fetch_arxiv

        keywords = req.keywords or []
        search_query = req.query or "cat:cs.CV"
        raw = fetch_arxiv.fetch_papers(
            search_query=search_query, keywords=keywords, max_results=req.max_results
        )
        inserted = 0
        for paper in raw:
            if await db.database.insert_paper(paper, space_id=space_id):
                inserted += 1
        return {
            "success": True,
            "papers": raw,
            "inserted": inserted,
            "count": len(raw),
        }
    except Exception as exc:
        raise APIError(str(exc), code="FETCH_FAILED")


@router.delete("/{paper_id}")
async def delete_paper(paper_id: str, space_id: str = Depends(get_space_id)):
    try:
        ok = await db.database.delete_paper(paper_id, space_id=space_id)
        return {"success": ok, "deleted": ok}
    except Exception as exc:
        raise APIError(str(exc), code="DELETE_FAILED")


@router.post("/{paper_id}/download")
async def download_pdf(paper_id: str, space_id: str = Depends(get_space_id)):
    try:
        from scripts import fetch_arxiv

        paper = await db.database.get_paper_by_id(paper_id, space_id=space_id)
        if not paper:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "NOT_FOUND", "message": "Paper not found"},
            )
        arxiv_id = paper.get("arxivId")
        pdf_url = paper.get("pdfUrl")
        if not arxiv_id or not pdf_url:
            raise APIError("Paper missing arxivId or pdfUrl", code="INVALID_PAPER")
        # 按空间归档：data/papers/<space_id>/pdfs/
        local_path = fetch_arxiv.download_pdf(arxiv_id, pdf_url, config.DATA_DIR, space_id=space_id)
        if not local_path:
            raise APIError("PDF download failed", code="DOWNLOAD_FAILED")
        await db.database.update_paper(paper_id, {"localPath": local_path}, space_id=space_id)
        return {"success": True, "localPath": local_path}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="DOWNLOAD_FAILED")


@router.post("/{paper_id}/summarize")
async def summarize_paper(paper_id: str, space_id: str = Depends(get_space_id)):
    try:
        from scripts.summarize_paper import build_summary_prompt, generate_fallback_summary

        paper = await db.database.get_paper_by_id(paper_id, space_id=space_id)
        if not paper:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "NOT_FOUND", "message": "Paper not found"},
            )

        prompt = build_summary_prompt(paper)
        summary = llm_client.call_llm(
            [
                {
                    "role": "system",
                    "content": "你是一个专业的学术论文分析助手，擅长总结计算机视觉和机器学习领域的论文。请用中文提供详细、有洞察力的论文总结。",
                },
                {"role": "user", "content": prompt},
            ]
        )
        source = "llm"
        if not summary:
            summary = generate_fallback_summary(paper)
            source = "fallback"

        await db.database.update_paper(paper_id, {"summary": summary}, space_id=space_id)
        return {"success": True, "summary": summary, "paperId": paper_id, "source": source}
    except Exception as exc:
        raise APIError(str(exc), code="SUMMARIZE_FAILED")


class BibtexUpdate(BaseModel):
    bibtex: str


@router.post("/{paper_id}/bibtex")
async def save_bibtex(
    paper_id: str, req: BibtexUpdate, space_id: str = Depends(get_space_id)
):
    """保存论文的 BibTeX 引用（论文中心「生成 BibTeX」工具回写）。"""
    try:
        paper = await db.database.get_paper_by_id(paper_id, space_id=space_id)
        if not paper:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "NOT_FOUND", "message": "Paper not found"},
            )
        ok = await db.database.update_paper(paper_id, {"bibtex": req.bibtex}, space_id=space_id)
        return {"success": ok, "paperId": paper_id}
    except Exception as exc:
        raise APIError(str(exc), code="BIBTEX_SAVE_FAILED")


__all__ = ["router"]
