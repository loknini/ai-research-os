"""RAG 检索路由。

数据接口（均按 ``space_id`` 软隔离）：
  * ``GET  /api/rag/capabilities``      -> 嵌入是否可用、当前嵌入模型、支持的文件类型
  * ``GET  /api/rag/sources``           -> 当前空间全部索引源（含进度/计数）
  * ``GET  /api/rag/sources/{id}``      -> 单个源详情 + 其下文档列表
  * ``GET  /api/rag/documents``         -> 文档列表（可按 sourceId 过滤）
  * ``POST /api/rag/index``             -> 提交一个或多个目标路径，后台索引
  * ``POST /api/rag/sources/{id}/reindex`` -> 清空并重索引某源
  * ``POST /api/rag/sources/{id}/cancel``   -> 取消进行中的索引
  * ``DELETE /api/rag/sources/{id}``    -> 删除源 + 级联文档/切片
  * ``POST /api/rag/query``             -> 检索 + 带引用回答
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .. import db
from ..deps import get_space_id
from ..errors import APIError
from ..llm import llm_client
from .. import rag_runner
from .. import rag_service
from ..schemas import RagIndexRequest, RagQueryRequest

router = APIRouter(prefix="/api/rag", tags=["rag"])

_SUPPORTED_TYPES = ["pdf", "txt", "md"]


@router.get("/capabilities")
async def capabilities(space_id: str = Depends(get_space_id)):
    return {
        "success": True,
        "embeddingsConfigured": llm_client.configured,
        "embeddingModel": llm_client.embedding_model,
        "supportedTypes": _SUPPORTED_TYPES,
        "pdfAvailable": _pypdf_available(),
    }


def _pypdf_available() -> bool:
    try:
        from pypdf import PdfReader  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


@router.get("/sources")
async def list_sources(space_id: str = Depends(get_space_id)):
    try:
        sources = await db.database.get_rag_sources(space_id=space_id)
        stats = await db.database.get_rag_stats(space_id=space_id)
        return {"success": True, "sources": sources, "stats": stats}
    except Exception as exc:
        raise APIError(str(exc), code="LIST_RAG_SOURCES_FAILED")


@router.get("/sources/{source_id}")
async def get_source(source_id: str, space_id: str = Depends(get_space_id)):
    try:
        source = await db.database.get_rag_source(source_id, space_id=space_id)
        if not source:
            return JSONResponse(status_code=404,
                                content={"success": False, "error": "NOT_FOUND",
                                         "message": "索引源不存在"})
        documents = await db.database.get_rag_documents(space_id=space_id, source_id=source_id)
        return {"success": True, "source": source, "documents": documents}
    except Exception as exc:
        raise APIError(str(exc), code="GET_RAG_SOURCE_FAILED")


@router.get("/documents")
async def list_documents(source_id: Optional[str] = None, space_id: str = Depends(get_space_id)):
    try:
        documents = await db.database.get_rag_documents(space_id=space_id, source_id=source_id)
        return {"success": True, "documents": documents}
    except Exception as exc:
        raise APIError(str(exc), code="LIST_RAG_DOCS_FAILED")


@router.post("/index")
async def index(req: RagIndexRequest, space_id: str = Depends(get_space_id)):
    paths = [p.strip() for p in (req.paths or []) if p and p.strip()]
    if not paths:
        raise APIError("paths 不能为空，请提供至少一个目标路径", code="INVALID_PATHS")
    file_types = req.fileTypes or _SUPPORTED_TYPES
    embed_model = (req.embedModel or "").strip() or None

    source_id = str(uuid.uuid4())
    name = paths[0] if len(paths) == 1 else f"多路径索引（{len(paths)} 个）"
    try:
        ok = await db.database.create_rag_source(
            source_id, space_id, name, paths, bool(req.recursive), file_types,
            embedding_model=embed_model or "", status="indexing")
        if not ok:
            raise APIError("创建索引源失败", code="CREATE_SOURCE_FAILED")
        # 后台索引：覆盖所有目标路径。
        await rag_runner.submit_index(
            source_id, space_id, paths, bool(req.recursive), file_types, embed_model)
        source = await db.database.get_rag_source(source_id, space_id=space_id)
        return {"success": True, "source": source}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="RAG_INDEX_FAILED")


@router.post("/sources/{source_id}/reindex")
async def reindex(source_id: str, space_id: str = Depends(get_space_id)):
    try:
        source = await db.database.get_rag_source(source_id, space_id=space_id)
        if not source:
            return JSONResponse(status_code=404,
                                content={"success": False, "error": "NOT_FOUND",
                                         "message": "索引源不存在"})
        # 清空旧文档与切片，重置计数，重新提交后台索引。
        async with db.database.get_db() as conn:  # type: ignore[attr-defined]
            await conn.execute(
                "DELETE FROM rag_chunks WHERE source_id = ? AND space_id = ?", (source_id, space_id))
            await conn.execute(
                "DELETE FROM rag_documents WHERE source_id = ? AND space_id = ?", (source_id, space_id))
        await db.database.update_rag_source(
            source_id, space_id, status="indexing", doc_count=0, chunk_count=0,
            error=None)
        await rag_runner.submit_index(
            source_id, space_id, source["targetPaths"], bool(source["recursive"]),
            source["fileTypes"], source.get("embeddingModel") or None)
        return {"success": True, "source": await db.database.get_rag_source(source_id, space_id=space_id)}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="RAG_REINDEX_FAILED")


@router.post("/sources/{source_id}/cancel")
async def cancel(source_id: str, space_id: str = Depends(get_space_id)):
    try:
        source = await db.database.get_rag_source(source_id, space_id=space_id)
        if not source:
            return JSONResponse(status_code=404,
                                content={"success": False, "error": "NOT_FOUND",
                                         "message": "索引源不存在"})
        ok = await rag_runner.cancel_index(source_id, space_id)
        return {"success": ok, "cancelled": ok}
    except Exception as exc:
        raise APIError(str(exc), code="RAG_CANCEL_FAILED")


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str, space_id: str = Depends(get_space_id)):
    try:
        ok = await db.database.delete_rag_source(source_id, space_id=space_id)
        return {"success": ok, "deleted": ok}
    except Exception as exc:
        raise APIError(str(exc), code="RAG_DELETE_FAILED")


@router.post("/query")
async def query(req: RagQueryRequest, space_id: str = Depends(get_space_id)):
    question = (req.question or "").strip()
    if not question:
        raise APIError("question 不能为空", code="INVALID_QUESTION")
    top_k = max(1, min(int(req.topK or 5), 20))
    try:
        result = await rag_service.query(space_id, question, top_k, req.sourceIds)
        return {"success": True, **result}
    except Exception as exc:
        raise APIError(str(exc), code="RAG_QUERY_FAILED")


__all__ = ["router"]
