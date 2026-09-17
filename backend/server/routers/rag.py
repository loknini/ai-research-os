"""RAG 检索路由。

数据接口（均按 ``space_id`` 软隔离）：
  * ``GET  /api/rag/capabilities``      -> 嵌入是否可用、当前嵌入模型、支持的文件类型
  * ``GET  /api/rag/sources``           -> 当前空间全部索引源（含进度/计数，三类 kind）
  * ``GET  /api/rag/sources/{id}``      -> 单个源详情 + 其下文档列表
  * ``GET  /api/rag/documents``         -> 文档列表（可按 sourceId 过滤）
  * ``POST /api/rag/index``             -> 提交一个或多个本地目标路径，后台索引（kind=local）
  * ``POST /api/rag/web``               -> 粘贴 URL 入库（P0 无递归爬取，守规单页抓取）
  * ``POST /api/rag/papers/{paper_id}/index`` -> 单篇论文手动索引（自动联动失败时补救）
  * ``POST /api/rag/sources/{id}/reindex`` -> 清空并重索引某源（系统源仅 local 可重建）
  * ``POST /api/rag/sources/{id}/cancel``   -> 取消进行中的索引
  * ``DELETE /api/rag/sources/{id}``    -> 删除源 + 级联文档/切片（系统源禁止删除）
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
from .. import vector_index as _vindex
from .. import vec_store
from ..schemas import RagIndexRequest, RagQueryRequest, RagWebRequest

router = APIRouter(prefix="/api/rag", tags=["rag"])

_SUPPORTED_TYPES = ["pdf", "txt", "md"]

_SYSTEM_SOURCES = {rag_service.PAPER_SOURCE_ID, rag_service.WEB_SOURCE_ID}


@router.get("/capabilities")
async def capabilities(space_id: str = Depends(get_space_id)):
    from .. import config
    eff = config.get_effective_llm_settings()
    return {
        "success": True,
        "embeddingsConfigured": llm_client.configured,
        "embeddingModel": llm_client.embedding_model,
        "embedProvider": eff.get("embedProvider", ""),
        "embedLocalModel": eff.get("embedLocalModel", ""),
        "embedLocalRevision": eff.get("embedLocalRevision", ""),
        "embedLocalAvailable": _local_model_available(),
        "supportedTypes": _SUPPORTED_TYPES,
        "pdfAvailable": _pdf_available(),
        "vectorBackend": "sqlite-vec" if vec_store.available() else "streaming-brute",
        "faissAvailable": _vindex.faiss_available(),
        "sourceKinds": ["local", "paper", "web"],
    }


def _pdf_available() -> bool:
    try:
        import pymupdf  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _local_model_available() -> bool:
    """检查本地嵌入模型是否已配置。"""
    from .. import config
    eff = config.get_effective_llm_settings()
    model_path = (eff.get("embedLocalModel") or "").strip()
    return bool(model_path)


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

    source_id = str(uuid.uuid4())
    name = paths[0] if len(paths) == 1 else f"多路径索引（{len(paths)} 个）"
    try:
        ok = await db.database.create_rag_source(
            source_id, space_id, name, paths, bool(req.recursive), file_types,
            status="indexing", kind="local")
        if not ok:
            raise APIError("创建索引源失败", code="CREATE_SOURCE_FAILED")
        # 后台索引：覆盖所有目标路径（嵌入模型一律走全局配置）。
        await rag_runner.submit_index(
            source_id, space_id, paths, bool(req.recursive), file_types)
        source = await db.database.get_rag_source(source_id, space_id=space_id)
        return {"success": True, "source": source}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="RAG_INDEX_FAILED")


@router.post("/web")
async def index_web(req: RagWebRequest, space_id: str = Depends(get_space_id)):
    """粘贴 URL 入库（P0：无递归爬取）。去重、单页抓取失败仅记 skipped。"""
    urls = [u.strip() for u in (req.urls or []) if u and u.strip()]
    if not urls:
        raise APIError("urls 不能为空，请粘贴至少一个 http(s) 链接", code="INVALID_URLS")
    if len(urls) > 20:
        raise APIError("单次最多提交 20 个 URL", code="TOO_MANY_URLS")
    try:
        job_id = await rag_runner.submit_web(urls, space_id)
        source = await db.database.get_rag_source(rag_service.WEB_SOURCE_ID, space_id=space_id)
        return {"success": True, "source": source, "status": "queued", "jobId": job_id}
    except Exception as exc:
        raise APIError(str(exc), code="RAG_WEB_FAILED")


@router.post("/papers/{paper_id}/index")
async def index_paper_route(paper_id: str, space_id: str = Depends(get_space_id)):
    """单篇论文手动索引（自动联动失败时的补救入口）。"""
    try:
        job_id = await rag_runner.submit_paper(paper_id, space_id)
        source = await db.database.get_rag_source(rag_service.PAPER_SOURCE_ID, space_id=space_id)
        return {"success": True, "source": source, "status": "queued", "jobId": job_id}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="RAG_PAPER_FAILED")


@router.post("/sources/{source_id}/reindex")
async def reindex(source_id: str, space_id: str = Depends(get_space_id)):
    import traceback as _tb
    try:
        source = await db.database.get_rag_source(source_id, space_id=space_id)
        if not source:
            return JSONResponse(status_code=404,
                                content={"success": False, "error": "NOT_FOUND",
                                         "message": "索引源不存在"})
        if source_id in _SYSTEM_SOURCES or (source.get("kind") in ("paper", "web")):
            raise APIError("系统源（论文库/网页）不支持整体重建，请逐条管理文档",
                           code="SYSTEM_SOURCE_READONLY")
        # 新代在后台完整构建，成功后一次切换；重建期间旧代继续提供检索。
        await db.database.update_rag_source(
            source_id, space_id, status="indexing", progress=0, total_files=0, error="")
        await rag_runner.submit_index(
            source_id, space_id, source["targetPaths"], bool(source["recursive"]),
            source["fileTypes"])
        return {"success": True, "source": await db.database.get_rag_source(source_id, space_id=space_id)}
    except APIError:
        raise
    except Exception as exc:
        _tb.print_exc()
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
    import traceback as _tb
    try:
        if source_id in _SYSTEM_SOURCES:
            raise APIError("系统源（论文库/网页）不支持删除，请逐条管理文档",
                           code="SYSTEM_SOURCE_READONLY")
        src = await db.database.get_rag_source(source_id, space_id=space_id)
        if src and src.get("kind") in ("paper", "web"):
            raise APIError("系统源（论文库/网页）不支持删除，请逐条管理文档",
                           code="SYSTEM_SOURCE_READONLY")
        ok = await db.database.delete_rag_source(source_id, space_id=space_id)
        return {"success": ok, "deleted": ok}
    except APIError:
        raise
    except Exception as exc:
        _tb.print_exc()
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
