"""内置核心工具（注册到 tool_registry）。

原 ``scripts/chat_agent_stream.py`` 里硬编码在 ``execute_tool`` 的 5 个工具
迁移到这里，用 ``@register_tool`` 声明式注册 —— 新增工具只需新增一个装饰器函数，
主循环 / Chat 路由无需改动。

策略标注（policy）：
* ``fetch_papers`` / ``get_stats`` —— safe（只读）
* ``create_task`` / ``create_project`` / ``create_note`` —— sensitive（写库，
  默认 auto 模式直接执行；manual / strict 模式等待用户审批）
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import time
from typing import Any, Dict, Optional

from scripts import database  # 顶层 scripts 包（正规导入，无 sys.path hack）

from ..tool_registry import POLICY_SAFE, POLICY_SENSITIVE, register_tool

# 跨上下文 DB 执行器：把数据库协程跑完并返回结果。
# 独立 CLI / Chat 同步生成器线程（无 running loop）-> asyncio.run；
# Agent runner 线程（已有 running loop）-> 提交到专用线程池，避免
# "asyncio.run() cannot be called from a running event loop" 崩溃。
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="tool-db"
)


def run_coro_sync(coro):
    """在任意上下文（有无 running loop）执行 DB 协程并返回结果。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    fut = _EXECUTOR.submit(asyncio.run, coro)
    return fut.result()


def _resolve_space(space_id: Optional[str]) -> str:
    return space_id if space_id is not None else database.DEFAULT_SPACE


@register_tool(
    "fetch_papers",
    description="从 arXiv 抓取与关键词相关的论文列表",
    parameters={
        "type": "object",
        "properties": {
            "keywords": {"type": "string", "description": "搜索关键词，例如 'transformer'"},
            "max_results": {"type": "integer", "description": "最大返回数量", "default": 10},
        },
        "required": ["keywords"],
    },
    policy=POLICY_SAFE,
)
def fetch_papers(params: Dict[str, Any], space_id: Optional[str] = None) -> Dict[str, Any]:
    """获取论文列表：引导模型使用专用技能（web_search / arxiv_reader）获取实时数据。"""
    keywords = params.get("keywords", "")
    return {
        "success": False,
        "message": (
            f"fetch_papers 已停用直接抓取，请改用技能工具 `web_search`（联网搜索）"
            f"或 `arxiv_reader`（读取 arXiv 论文）获取关键词「{keywords}」的论文信息。"
        ),
    }


@register_tool(
    "create_task",
    description="创建一个新的任务",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "任务标题"},
            "description": {"type": "string", "description": "任务描述"},
            "priority": {
                "type": "string",
                "description": "优先级",
                "enum": ["low", "medium", "high", "urgent"],
            },
        },
        "required": ["title", "description"],
    },
    policy=POLICY_SENSITIVE,
)
def create_task(params: Dict[str, Any], space_id: Optional[str] = None) -> Dict[str, Any]:
    now = int(time.time() * 1000)
    task_id = str(now)
    task = {
        "id": task_id,
        "title": params.get("title", "新任务"),
        "description": params.get("description", ""),
        "status": "todo",
        "priority": params.get("priority", "medium"),
        "deadline": None,
        "tags": [],
        "createdAt": now,
        "updatedAt": now,
    }
    success = run_coro_sync(database.insert_task(task, space_id=_resolve_space(space_id)))
    return {
        "success": success,
        "id": task_id,
        "title": task["title"],
        "message": f"任务「{task['title']}」已创建（id: {task_id}）" if success else "创建失败",
    }


@register_tool(
    "create_project",
    description="创建一个新的软件项目",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "项目名称"},
            "description": {"type": "string", "description": "项目描述"},
        },
        "required": ["name", "description"],
    },
    policy=POLICY_SENSITIVE,
)
def create_project(params: Dict[str, Any], space_id: Optional[str] = None) -> Dict[str, Any]:
    now = int(time.time() * 1000)
    project_id = str(now)
    project = {
        "id": project_id,
        "name": params.get("name", "新项目"),
        "description": params.get("description", ""),
        "techStack": [],
        "status": "design",
        "createdAt": now,
        "updatedAt": now,
    }
    success = run_coro_sync(database.insert_project(project, space_id=_resolve_space(space_id)))
    return {
        "success": success,
        "id": project_id,
        "name": project["name"],
        "message": f"项目「{project['name']}」已创建（id: {project_id}）" if success else "创建失败",
    }


@register_tool(
    "create_note",
    description="创建一篇知识笔记",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "笔记标题"},
            "content": {"type": "string", "description": "笔记正文内容"},
        },
        "required": ["title", "content"],
    },
    policy=POLICY_SENSITIVE,
)
def create_note(params: Dict[str, Any], space_id: Optional[str] = None) -> Dict[str, Any]:
    now = int(time.time() * 1000)
    note_id = str(now)
    note = {
        "id": note_id,
        "title": params.get("title", "新笔记"),
        "content": params.get("content", ""),
        "type": "note",
        "tags": [],
        "createdAt": now,
        "updatedAt": now,
    }
    success = run_coro_sync(database.insert_note(note, space_id=_resolve_space(space_id)))
    return {
        "success": success,
        "id": note_id,
        "title": note["title"],
        "message": f"笔记「{note['title']}」已创建（id: {note_id}）" if success else "创建失败",
    }


@register_tool(
    "get_stats",
    description="获取系统的统计数据（例如论文数量）",
    parameters={"type": "object", "properties": {}},
    policy=POLICY_SAFE,
)
def get_stats(params: Dict[str, Any], space_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        paper_count = run_coro_sync(
            database.get_papers_count(space_id=_resolve_space(space_id))
        )
        return {"success": True, "stats": {"papers": paper_count}}
    except Exception as exc:  # noqa: BLE001 - 统计失败不致命
        return {"success": False, "message": f"获取统计失败: {exc}"}


__all__ = ["run_coro_sync", "fetch_papers", "create_task", "create_project", "create_note", "get_stats"]
