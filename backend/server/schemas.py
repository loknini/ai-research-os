"""Pydantic request/response models shared across routers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Request body for ``POST /api/chat/completions``."""

    messages: List[dict] = []
    message: Optional[str] = None
    system_prompt: Optional[str] = None
    # RAG 文档检索接地：开启后后端会先用用户最新提问检索已索引文档，
    # 把相关片段注入系统提示并要求模型用 [n] 标注引用，同时回传 citations 事件。
    rag_enabled: bool = False
    rag_source_ids: Optional[List[str]] = None


class AgentRunRequest(BaseModel):
    """Request body for ``POST /api/agent/run`` and ``/api/agent/collaborate``.

    Frontend ``agent-workflow.tsx`` sends ``requirement`` (+ ``workflow``);
    ``aiAgent.ts`` historically sent ``message`` (+ ``system_prompt``).  Both are
    supported.
    """

    requirement: str = ""
    message: Optional[str] = None
    workflow: str = "workflow"
    projectId: Optional[str] = None
    roles: Optional[List[str]] = None


class ApprovalDecision(BaseModel):
    """Request body for ``POST /api/agent/runs/{run_id}/approvals/{approval_id}``."""

    approved: bool = True


class SessionCreate(BaseModel):
    """Request body for ``POST /api/agent/sessions``."""

    projectId: Optional[str] = None
    sessionType: str = "multi_agent_workflow"
    inputData: Optional[Dict[str, Any]] = None


class FetchPapersRequest(BaseModel):
    """Request body for ``POST /api/papers/fetch``."""

    keywords: Optional[List[str]] = None
    query: Optional[str] = None
    max_results: int = 10


class RagIndexRequest(BaseModel):
    """Request body for ``POST /api/rag/index``.

    ``paths`` 支持一个或多个目标路径（文件或目录）；``fileTypes`` 为空则接受全部
    受支持类型（pdf/txt/md）。``embedModel`` 可选，留空则用全局嵌入模型配置。
    """

    paths: List[str] = []
    recursive: bool = True
    fileTypes: Optional[List[str]] = None
    embedModel: Optional[str] = None


class RagQueryRequest(BaseModel):
    """Request body for ``POST /api/rag/query``."""

    question: str = ""
    topK: int = 5
    sourceIds: Optional[List[str]] = None


__all__ = ["ChatRequest", "AgentRunRequest", "SessionCreate", "FetchPapersRequest",
           "RagIndexRequest", "RagQueryRequest"]
