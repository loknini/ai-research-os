#!/usr/bin/env python3
"""
AI 聊天 Agent - 流式输出版本（使用原生 OpenAI function calling）

通过 stdout 输出 SSE 格式的数据。

本模块：
  * 导出 ``SYSTEM_PROMPT``（系统提示词，不再包含 <tool>...</tool> 正则格式）
  * 导出 ``TOOLS``（OpenAI 函数调用格式的工具描述列表）
  * 导出 ``execute_tool(tool_name, parameters, space_id=None)``（正确的工具执行器，支持空间隔离）
  * 提供 ``stream_chat(messages)``（CLI / 遗留路径），使用原生 function calling

后端路由 ``backend/server/routers/chat.py`` 直接复用 ``SYSTEM_PROMPT`` /
``TOOLS`` / ``execute_tool``，并通过 ``backend.server.llm.LLMClient.stream_llm``
完成可配置的流式调用与工具执行。
"""

import os
import sys
import json
import urllib.request
import urllib.error

# 保证 LLMUnavailableError 始终可用（独立 CLI 运行时后端可能不可达）。
try:  # pragma: no cover - 后端可达时走此分支
    from backend.server.llm import LLMUnavailableError
except Exception:  # pragma: no cover - 独立 CLI 回退
    class LLMUnavailableError(Exception):
        """与 backend.server.llm.LLMUnavailableError 契约一致的回退异常。"""


# LLM 端点配置（仅用于独立 CLI 回退路径）
HTTP_URL = os.environ.get('LLM_HTTP_URL', os.environ.get('LLM_BASE_URL', 'http://localhost:11434/v1'))
GATEWAY_TOKEN = os.environ.get('LLM_API_KEY', '')

# SkillBridge：后端 Agent 可调用的技能（manifest 驱动，subprocess 执行）
# 与 llm 回退一致：后端可达时导入真实模块；独立 CLI 不可达时退化为"无技能"。
try:  # pragma: no cover - 后端可达时走此分支
    from backend.server.skills_bridge import get_skill_tools, is_skill_tool, invoke_skill
except Exception:  # pragma: no cover - 独立 CLI 回退
    def get_skill_tools():
        return []
    def is_skill_tool(name):
        return False
    def invoke_skill(name, params, space_id="__default__"):
        return {"success": False, "error": "skills_bridge 不可用"}

# 工具注册表（插件化 + 审批策略）：后端可达时 TOOLS / execute_tool 全部委托给
# 注册表；独立 CLI 不可达时退化为下方静态实现（无审批，保持向后兼容）。
try:  # pragma: no cover - 后端可达时走此分支
    from backend.server.tool_registry import (
        execute as _registry_execute,
        get_tools as _registry_tools,
    )

    _HAS_REGISTRY = True
except Exception:  # pragma: no cover - 独立 CLI 回退
    _HAS_REGISTRY = False

# 系统提示词（使用原生 function calling，不再使用 <tool>...</tool> 正则格式）
SYSTEM_PROMPT = """你是 AI Research OS 的智能助手，专门帮助研究人员管理论文、任务、项目和实验。

你可以使用以下工具来帮助用户：
1. **fetch_papers** - 从 arXiv 抓取论文（参数：keywords 关键词，max_results 最大数量）
2. **create_task** - 创建新任务（参数：title 标题，description 描述，priority 优先级）
3. **create_project** - 创建软件项目（参数：name 名称，description 描述）
4. **create_note** - 创建知识笔记（参数：title 标题，content 内容）
5. **get_stats** - 获取系统统计数据（无参数）

当用户请求你执行上述操作时，请通过工具（tools）接口调用对应的工具，由系统负责执行并反馈结果；不要自行拼装工具调用文本。只有在需要直接向用户解释或回答问题时才输出自然语言文本。

**绝对铁律（回复前必须自检）**：
1. 任何关于"创建""保存""生成""记录"的陈述，必须基于本回合确实发生了对应的工具调用（function_call）。如果本回合没有调用 `create_note` / `create_task` / `create_project` 等写入工具，你就**禁止**说"已为你创建""已为你保存""已生成笔记《xxx》""已创建任务""已记录"等任何暗示数据已写入系统的措辞。
2. 如果你只是回答了用户的问题、做了总结、给了建议，但**没有实际调用工具**，请直接陈述事实或给出分析，绝不要伪造"我已经帮你创建/保存了..."之类的结果。
3. 回复前请自检：本回合是否有 tool_call？若没有，则把所有含"已""已经""已为你"的创建类表述全部删除。
4. **若本回合确实调用了写入工具**，最终回复请使用可验证的精确表述，例如："已调用 `create_note` 工具创建笔记《title》（id: xxx），可在知识库查看。"、"已调用 `create_task` 工具创建任务《title》（id: xxx）。"、"已调用 `create_project` 工具创建项目《name》（id: xxx）。"**禁止**使用模糊的"已为你创建详细笔记"等无法对应到具体工具与 id 的表述。

**禁止出现的幻觉表述示例**："我已为你创建了详细的知识笔记""已为你创建详细笔记《xxx》""已经为你生成研究任务""已保存到系统""已记录"等。

此外，系统可能注册了额外的**技能（skill）**工具（其能力见各工具 description，例如代码评审 `code_review`）。当用户的诉求匹配某个技能时，直接调用对应技能工具即可——指令型技能会把操作指引回灌给你，照着用既有工具执行。

请用中文回答，保持专业、友好且简洁。"""


# OpenAI 函数调用格式的工具描述（静态 5 个）
STATIC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_papers",
            "description": "从 arXiv 抓取与关键词相关的论文列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "string",
                        "description": "搜索关键词，例如 'transformer' 或 'large language model'",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回数量",
                        "default": 10,
                    },
                },
                "required": ["keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "创建一个新的任务",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "任务标题",
                    },
                    "description": {
                        "type": "string",
                        "description": "任务描述",
                    },
                    "priority": {
                        "type": "string",
                        "description": "优先级：low / medium / high / urgent",
                        "enum": ["low", "medium", "high", "urgent"],
                    },
                },
                "required": ["title", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_project",
            "description": "创建一个新的软件项目",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "项目名称",
                    },
                    "description": {
                        "type": "string",
                        "description": "项目描述",
                    },
                },
                "required": ["name", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_note",
            "description": "创建一篇知识笔记",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "笔记标题",
                    },
                    "content": {
                        "type": "string",
                        "description": "笔记正文内容",
                    },
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stats",
            "description": "获取系统的统计数据（例如论文数量）",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]

# 工具清单：后端可达时来自注册表（内置工具 + 技能工具），否则静态 5 个 + 技能。
TOOLS = _registry_tools() if _HAS_REGISTRY else STATIC_TOOLS + get_skill_tools()


# 数据库操作通过正规包导入（scripts 为正规包，无 sys.path hack）

# 延迟导入数据库模块（已迁移到 aiosqlite 异步）
def _run_db(coro):
    """在 chat 同步生成器线程中运行 DB 协程。

    chat 路由的 ``event_stream`` 是同步生成器（Starlette 在线程池中迭代），
    因此此处 ``asyncio.run`` 会新建并独占一个事件循环，与后端主事件循环隔离，
    安全可用。
    """
    import asyncio
    return asyncio.run(coro)


def execute_tool(tool_name: str, parameters: dict, space_id: str | None = None,
                 approve=None, mode: str | None = None) -> dict:
    """执行工具调用。

    后端可达时委托给 ``backend.server.tool_registry.execute``（含审批策略与
    插件注册表）；独立 CLI 回退到下方静态实现。

    写入型工具（create_task/create_project/create_note）按传入的 ``space_id`` 落到
    对应空间；未传入时回退到默认空间 ``__default__``，保持向后兼容。

    技能类工具优先派发到 SkillBridge（subprocess 执行，独立且无需本地 DB）。
    """
    if _HAS_REGISTRY:
        return _registry_execute(tool_name, parameters, space_id=space_id,
                                 approve=approve, mode=mode)
    return _legacy_execute_tool(tool_name, parameters, space_id)


def _legacy_execute_tool(tool_name: str, parameters: dict, space_id: str | None = None) -> dict:
    """独立 CLI 回退实现（后端不可达时使用，不支持审批策略）。"""
    import database

    # 技能类工具：交给 SkillBridge 以 subprocess 执行（吃参数、吐 JSON）
    if is_skill_tool(tool_name):
        resolved_space = space_id if space_id is not None else database.DEFAULT_SPACE
        return invoke_skill(tool_name, parameters, resolved_space)

    try:
        import time
        now = int(time.time() * 1000)
        resolved_space = space_id if space_id is not None else database.DEFAULT_SPACE

        if tool_name == "create_task":
            task_id = str(now)
            task = {
                "id": task_id,
                "title": parameters.get("title", "新任务"),
                "description": parameters.get("description", ""),
                "status": "todo",
                "priority": parameters.get("priority", "medium"),
                "deadline": None,
                "tags": [],
                "createdAt": now,
                "updatedAt": now
            }
            success = _run_db(database.insert_task(task, space_id=resolved_space))
            return {
                "success": success,
                "id": task_id,
                "title": task["title"],
                "message": f"任务「{task['title']}」已创建（id: {task_id}）" if success else "创建失败"
            }

        elif tool_name == "create_project":
            project_id = str(now)
            project = {
                "id": project_id,
                "name": parameters.get("name", "新项目"),
                "description": parameters.get("description", ""),
                "techStack": [],
                "status": "design",
                "createdAt": now,
                "updatedAt": now
            }
            success = _run_db(database.insert_project(project, space_id=resolved_space))
            return {
                "success": success,
                "id": project_id,
                "name": project["name"],
                "message": f"项目「{project['name']}」已创建（id: {project_id}）" if success else "创建失败"
            }

        elif tool_name == "create_note":
            note_id = str(now)
            note = {
                "id": note_id,
                "title": parameters.get("title", "新笔记"),
                "content": parameters.get("content", ""),
                "type": "note",
                "tags": [],
                "createdAt": now,
                "updatedAt": now
            }
            success = _run_db(database.insert_note(note, space_id=resolved_space))
            return {
                "success": success,
                "id": note_id,
                "title": note["title"],
                "message": f"笔记「{note['title']}」已创建（id: {note_id}）" if success else "创建失败"
            }

        elif tool_name == "get_stats":
            try:
                paper_count = _run_db(database.get_papers_count(space_id=resolved_space))
                return {
                    "success": True,
                    "stats": {"papers": paper_count}
                }
            except Exception as e:
                return {"success": False, "message": f"获取统计失败: {str(e)}"}

        else:
            return {"success": False, "message": f"未知工具: {tool_name}"}

    except Exception as e:
        return {"success": False, "message": f"执行失败: {str(e)}"}


def _safe_json(arguments) -> dict:
    """将工具参数归一化为 dict（兼容已解析对象与增量 JSON 字符串）。"""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        if not arguments.strip():
            return {}
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return {}
    return arguments if isinstance(arguments, dict) else {}


def _legacy_stream(messages: list, tools=None):
    """独立 CLI 回退：委托唯一 LLM 客户端（避免与 llm.py 重复）。"""
    try:
        from backend.server.llm import llm_client as _client
    except Exception as exc:
        raise LLMUnavailableError(f"LLM 客户端不可用: {exc}") from exc
    yield from _client.stream_llm(messages, tools=tools)


def _run_stream(formatted_messages: list, streamer) -> None:
    """统一执行第一轮流式输出 + 工具执行 + 第二轮最终回答。

    ``streamer(messages, tools=None)`` 需产出与 ``LLMClient.stream_llm`` 相同的
    item 契约：逐块 ``str`` 文本增量，以及流结束后至多一个 ``{"tool_calls": [...]}``。
    """
    assistant_text = ""
    collected = []
    try:
        for item in streamer(formatted_messages, TOOLS):
            if isinstance(item, str):
                assistant_text += item
                print(json.dumps({"type": "text", "content": item}, ensure_ascii=False), flush=True)
            elif isinstance(item, dict) and "tool_calls" in item:
                collected = item["tool_calls"]
    except LLMUnavailableError as exc:
        print(json.dumps({"type": "error", "error": f"LLM 服务不可用：{exc}"}, ensure_ascii=False), flush=True)
        print('[DONE]', flush=True)
        return

    if collected:
        results = []
        for call in collected:
            name = call.get("name")
            params = _safe_json(call.get("arguments", {}))
            # 输出工具开始执行
            print(json.dumps({
                "type": "tool_start",
                "tool": name,
                "parameters": params,
            }, ensure_ascii=False), flush=True)
            # 执行工具
            result = execute_tool(name, params)
            # 输出工具执行结果
            print(json.dumps({
                "type": "tool_result",
                "tool": name,
                "result": result,
            }, ensure_ascii=False), flush=True)
            results.append((call.get("id", ""), name, result, call.get("arguments", {})))

        # 构造第二轮对话：把助手消息（含 tool_calls）与工具结果回灌给模型
        updated_messages = list(formatted_messages)
        updated_messages.append({
            "role": "assistant",
            "content": assistant_text,
            "tool_calls": [
                {
                    "id": cid,
                    "type": "function",
                    "function": {
                        "name": cname,
                        "arguments": json.dumps(_safe_json(args), ensure_ascii=False),
                    },
                }
                for (cid, cname, _res, args) in results
            ],
        })
        for cid, cname, res, _args in results:
            updated_messages.append({
                "role": "tool",
                "tool_call_id": cid,
                "content": json.dumps(res, ensure_ascii=False),
            })

        # 第二轮：仅消费文本增量（工具已在上一轮执行）
        try:
            for item2 in streamer(updated_messages, None):
                if isinstance(item2, str):
                    print(json.dumps({"type": "text", "content": item2}, ensure_ascii=False), flush=True)
        except LLMUnavailableError as exc:
            print(json.dumps({"type": "error", "error": f"LLM 服务不可用：{exc}"}, ensure_ascii=False), flush=True)

    print('[DONE]', flush=True)


def stream_chat(messages):
    """流式聊天，输出 SSE 格式数据，使用原生 OpenAI function calling。

    优先使用可配置的 ``backend.server.llm.LLMClient``（与 chat.py 路由一致）；
    无法导入后端时回退到 stdlib urllib 直接请求（独立 CLI 运行）。
    """
    # 确保消息格式正确，并在开头插入系统提示词
    formatted_messages = []
    for msg in messages:
        role = msg.get('role', 'user')
        content = msg.get('content', '')
        if role != 'system':  # 过滤掉系统消息，我们用自己的
            formatted_messages.append({"role": role, "content": content})
    formatted_messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

    try:  # pragma: no cover - 后端可达时走此分支
        from backend.server.llm import llm_client
        streamer = lambda msgs, tools=None: llm_client.stream_llm(msgs, tools=tools)
    except Exception:  # pragma: no cover - 独立 CLI 回退
        streamer = _legacy_stream

    _run_stream(formatted_messages, streamer)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No messages provided"}, ensure_ascii=False))
        sys.exit(1)

    try:
        messages = json.loads(sys.argv[1])
        stream_chat(messages)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {str(e)}"}, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
