"""路由共享的 Pydantic 请求/响应模型。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """``POST /api/chat/completions`` 请求体。"""

    messages: List[dict] = []
    message: Optional[str] = None
    system_prompt: Optional[str] = None
    # RAG 文档检索接地：开启后后端会先用用户最新提问检索已索引文档，
    # 把相关片段注入系统提示并要求模型用 [n] 标注引用，同时回传 citations 事件。
    rag_enabled: bool = False
    rag_source_ids: Optional[List[str]] = None


class AgentRunRequest(BaseModel):
    """``POST /api/agent/runs`` 请求体。

    ``teamId`` 选择已快照的 DAG；未提供时，旧角色管线仍支持 ``roles`` 和历史
    ``message`` 别名。
    """

    requirement: str = ""
    message: Optional[str] = None
    workflow: str = "workflow"
    projectId: Optional[str] = None
    roles: Optional[List[str]] = None
    teamId: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class ApprovalDecision(BaseModel):
    """``POST /api/agent/runs/{run_id}/approvals/{approval_id}`` 请求体。"""

    approved: bool = True


class SessionCreate(BaseModel):
    """``POST /api/agent/sessions`` 请求体。"""

    projectId: Optional[str] = None
    sessionType: str = "multi_agent_workflow"
    inputData: Optional[Dict[str, Any]] = None


class FetchPapersRequest(BaseModel):
    """``POST /api/papers/fetch`` 请求体。"""

    keywords: Optional[List[str]] = None
    query: Optional[str] = None
    max_results: int = 10
    dry_run: bool = False


class BatchImportPapersRequest(BaseModel):
    """``POST /api/papers/batch`` 请求体。"""

    papers: List[Dict[str, Any]] = []


class RagIndexRequest(BaseModel):
    """``POST /api/rag/index`` 请求体。

    ``paths`` 支持一个或多个目标路径（文件或目录）；``fileTypes`` 为空则接受全部
    受支持类型（pdf/txt/md）。嵌入模型一律走全局 LLM 配置（单空间单向量空间，
    不支持按源覆盖）。
    """

    paths: List[str] = []
    recursive: bool = True
    fileTypes: Optional[List[str]] = None


class RagWebRequest(BaseModel):
    """``POST /api/rag/web`` 请求体（P0：用户粘贴 URL，无递归爬取）。"""

    urls: List[str] = []


class RagQueryRequest(BaseModel):
    """``POST /api/rag/query`` 请求体。"""

    question: str = ""
    topK: int = 5
    sourceIds: Optional[List[str]] = None


__all__ = ["ChatRequest", "AgentRunRequest", "SessionCreate", "FetchPapersRequest",
           "RagIndexRequest", "RagWebRequest", "RagQueryRequest"]
