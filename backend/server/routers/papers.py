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

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse
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
async def fetch_papers(
    space_id: str = Depends(get_space_id),
    req: Optional[FetchPapersRequest] = None,
    max_results_q: Optional[int] = Query(None, alias="max", ge=1, le=100),
    keywords_q: Optional[str] = Query(None, alias="keywords"),
):
    """从 arXiv 抓取论文并入库。

    兼容两种调用方式（query 参数优先于 body）：

    * 前端现状契约：``POST /api/papers/fetch?max=10&keywords=image+generation``（无 body）
    * body 契约：``POST /api/papers/fetch`` + JSON ``{"keywords": [...], "query": "...", "max_results": 10}``

    ``keywords`` query 参数支持逗号分隔多个关键词；单个值（含空格）整体视为一个
    短语关键词（arXiv 的 ``all:`` 字段支持短语匹配）。
    """
    try:
        from scripts import fetch_arxiv

        max_results = max_results_q if max_results_q is not None else (req.max_results if req else 10)

        keywords: list = []
        if keywords_q:
            keywords = [kw.strip() for kw in keywords_q.split(",") if kw.strip()]
        elif req is not None and req.keywords:
            keywords = list(req.keywords)

        search_query = (req.query if req else None) or "cat:cs.CV"
        raw = fetch_arxiv.fetch_papers(
            search_query=search_query, keywords=keywords, max_results=max_results
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
            # 前端 papersApi.ts 读取 result.total，这里一并返回保持契约兼容。
            "total": len(raw),
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


@router.get("/{arxiv_id}/pdf")
async def stream_pdf(arxiv_id: str, space_id: str = Depends(get_space_id)):
    """PDF 预览：流式返回二进制字节，供前端 react-pdf 渲染。

    修复（2026-08-25）：之前没有此路由，前端调 ``GET /api/papers/{arxivId}/pdf``
    返回 404 → react-pdf 永远停在 loading（``numPages=0``，工具栏一直显示 ``1 / 0``）。
    现在按空间软隔离 + 按需下载：localPath 不存在就调 ``fetch_arxiv.download_pdf``
    落盘，再用 ``FileResponse`` 返回 ``application/pdf`` 字节流。

    ``Content-Disposition: inline`` 告诉浏览器不要触发下载对话框，让
    ``<Document>`` 组件直接拿到 PDF 二进制做客户端渲染。
    """
    try:
        from pathlib import Path

        from scripts import fetch_arxiv

        paper = await db.database.get_paper_by_arxiv(arxiv_id, space_id=space_id)
        if not paper:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": "NOT_FOUND",
                    "message": f"Paper with arxiv id {arxiv_id} not found",
                },
            )

        local_path = paper.get("localPath")
        pdf_url = paper.get("pdfUrl")

        # 按需懒下载：首次预览或跨进程/跨 worker 时 localPath 为空
        if not local_path or not Path(local_path).exists():
            if not pdf_url:
                raise APIError("Paper missing localPath and pdfUrl", code="INVALID_PAPER")
            local_path = fetch_arxiv.download_pdf(
                arxiv_id, pdf_url, config.DATA_DIR, space_id=space_id
            )
            if not local_path:
                raise APIError("PDF download failed", code="DOWNLOAD_FAILED")
            # 回写 localPath，避免下次再下
            await db.database.update_paper(
                paper["id"], {"localPath": local_path}, space_id=space_id
            )

        if not Path(local_path).exists():
            raise APIError("PDF file missing on disk", code="FILE_MISSING")

        # ``inline`` 让浏览器不弹下载框，react-pdf 直接解析字节流
        return FileResponse(
            path=local_path,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{arxiv_id}.pdf"'},
        )
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="PDF_STREAM_FAILED")


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
