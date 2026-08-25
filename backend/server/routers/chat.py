"""Chat route -> SSE streaming via the in-process ``llm.py`` client.

Mirrors the legacy ``scripts/chat_agent_stream.py`` behaviour (system prompt +
tool calls) but performs the actual streaming through ``LLMClient.stream_llm``,
so the LLM endpoint is fully configurable and never spawns a subprocess.

本文件在原有 ReAct 循环基础上叠加了三项增强（对应近期需求）：
1. **指令型 skill 注入 system prompt**：指令型技能被调用时，把 SKILL.md 正文注入
   系统提示（仅一次），tool_result 改为精简确认，避免每段正文每轮重发浪费 token。
2. **上下文窗口记录 + 压缩**：每轮估算 token 用量并以 ``context`` 事件上报；超阈值时
   把中间历史摘要成单条 system 消息（保持 tool_call 配对不被切断、记忆上下文保留）。
3. **持久记忆注入**：从 ``X-Space-Key`` 解析空间，把该空间的长期记忆注入系统提示，
   实现「AI 越用越懂用户」。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..errors import SSE_DONE, sse_error
from ..llm import LLMUnavailableError, llm_client
from ..schemas import ChatRequest
from ..deps import normalize_space_key, DEFAULT_SPACE
from ..memory import memory_prompt
from .. import rag_service
from scripts.chat_agent_stream import SYSTEM_PROMPT, execute_tool, is_skill_tool, TOOLS

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 上下文窗口（token 估算）相关配置：统一实现见 backend/server/context.py，
# 此处保留旧名导出，Chat 路由其余代码无需改动。
from ..context import (
    CONTEXT_TOKEN_LIMIT,
    KEEP_LAST_MESSAGES,
    estimate_tokens as _estimate_tokens,
    summarize_history as _summarize,
    compact_messages as _compact,
)


# --------------------------------------------------------------------------- #
# /skill 命令解析
# --------------------------------------------------------------------------- #
def _extract_skill_command(req: ChatRequest):
    """识别手动 /skill 命令。命中则返回 ``(name, params)``，否则 ``None``。"""
    candidates: list = []
    if req.message:
        candidates.append(req.message)
    for m in reversed(req.messages or []):
        if m.get("role") == "user":
            candidates.append(_content_to_text(m.get("content", "")))
            break
    for text in candidates:
        if text and text.strip().startswith("/skill "):
            return _parse_skill_command(text.strip())
    return None


def _content_to_text(content: Any) -> str:
    """把消息 content 归一化为纯文本（兼容多模态数组：仅取 text part，忽略图片）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
        return "\n".join(p for p in parts if p)
    if content is None:
        return ""
    return str(content)


def _parse_skill_command(text: str):
    """把 ``/skill <name> [args]`` 解析成 (name, params)。"""
    rest = text[len("/skill "):].strip()
    if not rest:
        return None
    parts = rest.split(None, 1)
    name = parts[0]
    argstr = parts[1].strip() if len(parts) > 1 else ""
    if not argstr:
        return name, {}
    try:
        parsed = json.loads(argstr)
        if isinstance(parsed, dict):
            return name, parsed
    except json.JSONDecodeError:
        pass
    return name, {"input": argstr}


def _parse_tool_arguments(raw: Any) -> dict:
    """将工具参数归一化为 dict（兼容已解析对象与增量 JSON 字符串）。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _space_from_request(request: Request) -> str:
    """从 ``X-Space-Key`` 头解析空间；缺失则回落默认空间。"""
    return normalize_space_key(request.headers.get("X-Space-Key")) or DEFAULT_SPACE


def _extract_text_from_content(content) -> str:
    """从多模态 content（str 或 list of parts）提取纯文本，用于 RAG 检索等。
    图片 part 直接忽略（只取 text part），避免把 base64 噪声或占位符送进检索查询。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" and part.get("text"):
                    texts.append(str(part.get("text")))
        return "\n".join(t for t in texts if t)
    return str(content) if content else ""


def _last_user_message(req: ChatRequest) -> str:
    """取最近一条 user 消息作为 RAG 检索的查询（无则回退 req.message）。
    兼容多模态 content（list of parts）：只提取文本片段。"""
    for m in reversed(req.messages or []):
        if m.get("role") == "user":
            return _extract_text_from_content(m.get("content", ""))
    return req.message or ""


def _filter_cited_sources(answer_text: str, sources: List[dict]) -> List[dict]:
    """根据 assistant 回答中实际出现的 [n] 角标，过滤真正被引用的来源。

    这样可避免把检索 top-k 全部当成引用推给用户——只有模型确实在正文中标注 [n] 的来源
    才会出现在引用卡片里，抑制“为了引用而引用”。
    """
    if not sources or not answer_text:
        return []
    cited_ranks: set = set()
    for match in re.finditer(r"\[\s*(\d+)\s*\]", answer_text):
        try:
            cited_ranks.add(int(match.group(1)))
        except ValueError:
            continue
    if not cited_ranks:
        return []
    return [s for s in sources if int(s.get("rank", 0)) in cited_ranks]


# --------------------------------------------------------------------------- #
# 路由
# --------------------------------------------------------------------------- #
@router.post("/completions")
@router.post("/completions/stream")
async def chat_completions(req: ChatRequest, request: Request):
    space_id = _space_from_request(request)

    messages: List[dict] = list(req.messages or [])
    if req.message and not messages:
        messages.append({"role": "user", "content": req.message})
    if not messages:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "INVALID_REQUEST", "message": "messages required"},
        )

    # RAG 文档检索接地：开启时用用户最新提问检索已索引文档，把相关片段注入系统提示，
    # 并回传 citations 事件供前端展示出处。无命中则优雅降级（不注入、不报错）。
    rag_references_block: str = ""
    rag_sources_payload: List[dict] = []
    rag_mode = "off"
    if req.rag_enabled:
        question = _last_user_message(req)
        if question:
            try:
                hits, mode, _ = await rag_service.retrieve(
                    space_id, question, top_k=5, source_ids=req.rag_source_ids)
            except Exception:  # noqa: BLE001 - RAG 检索失败不应阻断正常对话
                hits, mode = [], "error"
            rag_mode = mode
            if hits:
                parts = [
                    f"[{h['rank']}] (来源: {h['fileName']} 第{h['pageStart']}页)\n{h['content']}"
                    for h in hits
                ]
                rag_references_block = (
                    "\n\n## 参考资料（以下为用户已索引的文档片段，请优先据此回答。"
                    "引用规则："
                    "1. 只在你确实使用了某条资料的内容时才在对应句子末尾标注 [n]，例如："
                    "\"该模型在 ImageNet 上取得了 90% 的准确率 [1]。\""
                    "2. 若资料与问题无关、无法支撑答案，或你直接基于自身知识回答，"
                    "则不要标注任何 [n]，并明确说明\"提供的参考资料中未找到相关信息\"。"
                    "3. 禁止为了形式而编造引用；只允许引用上面列出的资料编号。\n"
                    + "\n\n".join(parts)
                )
                rag_sources_payload = [{
                    "rank": h["rank"],
                    "fileName": h["fileName"],
                    "filePath": h["filePath"],
                    "fileType": h["fileType"],
                    "pageStart": h["pageStart"],
                    "pageEnd": h["pageEnd"],
                    "snippet": h["content"],
                    "score": h["score"],
                } for h in hits]

    # 系统提示 = 基础提示 + 该空间长期记忆 + RAG 参考资料
    system_content = (req.system_prompt or SYSTEM_PROMPT) + memory_prompt(space_id) + rag_references_block
    formatted = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role != "system":
            formatted.append({"role": role, "content": content})
    formatted.insert(0, {"role": "system", "content": system_content})

    MAX_TURNS = 6  # 防止模型无限循环调用工具的安全上限

    def event_stream():
        # —— 手动 /skill 命令：短路正常 ReAct 循环，直接执行并让 LLM 总结 —— #
        skill_cmd = _extract_skill_command(req)
        if skill_cmd is not None:
            name, params = skill_cmd
            if not is_skill_tool(name):
                yield sse_error(f"未找到已启用的技能: {name}")
                yield f"data: {SSE_DONE}\n\n"
                return
            yield f"data: {json.dumps({'type': 'tool_start', 'tool': name, 'parameters': params}, ensure_ascii=False)}\n\n"
            try:
                result = execute_tool(name, params, space_id=space_id)
            except Exception as exc:  # 防御性兜底
                result = {"success": False, "error": f"技能执行异常: {exc}"}
            yield f"data: {json.dumps({'type': 'tool_result', 'tool': name, 'result': result}, ensure_ascii=False)}\n\n"

            # 指令型技能：把正文注入系统提示（而非堆在 user 消息里反复重发）
            sys_content = SYSTEM_PROMPT + memory_prompt(space_id) + rag_references_block
            user_note = (
                f"用户通过 /skill 命令手动调用了技能「{name}」，"
                f"请遵循系统提示中的技能指引完成任务，并用简洁中文向用户说明结果。"
            )
            if result.get("type") == "instruction" and result.get("instructions"):
                sys_content += f"\n\n## 技能「{name}」操作指引\n{result['instructions']}"

            summary_msgs = [
                {"role": "system", "content": sys_content},
                {"role": "user", "content": user_note},
            ]
            summary_text: str = ""
            try:
                for item in llm_client.stream_llm(summary_msgs):
                    if isinstance(item, str):
                        summary_text += item
                        yield f"data: {json.dumps({'type': 'text', 'content': item}, ensure_ascii=False)}\n\n"
            except LLMUnavailableError as exc:
                yield sse_error(f"LLM 服务不可用：{exc}")

            # RAG 引用溯源：只在 LLM 实际引用后才把对应来源发给前端，避免 top-k 全部暴露。
            cited_sources = _filter_cited_sources(summary_text, rag_sources_payload)
            yield f"data: {json.dumps({'type': 'rag_sources', 'sources': cited_sources, 'mode': rag_mode, 'enabled': req.rag_enabled}, ensure_ascii=False)}\n\n"
            yield f"data: {SSE_DONE}\n\n"
            return

        # 多轮 ReAct 循环：每轮都携带 TOOLS，让模型可持续调用工具并基于结果反思，
        # 直到模型不再请求工具（产出最终自然语言回答）或达到 MAX_TURNS 上限。
        messages: List[dict] = list(formatted)
        injected_skills: set = set()  # 已注入 system prompt 的指令型技能（仅注入一次）
        final_answer_text: str = ""
        for _ in range(MAX_TURNS):
            # 上下文压缩（超阈值时把中间历史摘要为单条 system 消息）
            messages, compressed = _compact(messages)
            yield f"data: {json.dumps({'type': 'context', 'estimated_tokens': _estimate_tokens(messages), 'limit': CONTEXT_TOKEN_LIMIT, 'compressed': compressed}, ensure_ascii=False)}\n\n"

            assistant_text: str = ""
            tool_calls_this_turn: List[dict] = []
            try:
                for item in llm_client.stream_llm(messages, tools=TOOLS):
                    if isinstance(item, str):
                        assistant_text += item
                        yield f"data: {json.dumps({'type': 'text', 'content': item}, ensure_ascii=False)}\n\n"
                    elif isinstance(item, dict) and "tool_calls" in item:
                        tool_calls_this_turn = item["tool_calls"]
            except LLMUnavailableError as exc:
                yield sse_error(f"LLM 服务不可用：{exc}")
                yield f"data: {SSE_DONE}\n\n"
                return

            # 本轮没有请求工具 -> 已经是最终回答，结束循环
            if not tool_calls_this_turn:
                final_answer_text = assistant_text
                break

            # 执行本轮的工具调用
            results = []
            for call in tool_calls_this_turn:
                name = call.get("name")
                params = _parse_tool_arguments(call.get("arguments", {}))
                yield f"data: {json.dumps({'type': 'tool_start', 'tool': name, 'parameters': params}, ensure_ascii=False)}\n\n"
                result = execute_tool(name, params, space_id=space_id)

                # 指令型技能：正文注入 system prompt（仅一次），tool_result 改为精简确认
                if is_skill_tool(name) and result.get("type") == "instruction":
                    body = result.get("instructions", "")
                    if body and name not in injected_skills:
                        injected_skills.add(name)
                        sys_msg = messages[0]
                        if sys_msg.get("role") == "system":
                            sys_msg["content"] = (
                                sys_msg.get("content", "")
                                + f"\n\n## 已加载技能「{name}」操作指引\n{body}"
                            )
                    result_out = {
                        "success": True,
                        "skill": name,
                        "type": "instruction",
                        "note": (
                            f"已加载技能「{name}」的操作指引到系统提示中，请遵循其指示用既有工具执行，"
                            f"不要再调用该技能工具。"
                        ),
                    }
                else:
                    result_out = result

                yield f"data: {json.dumps({'type': 'tool_result', 'tool': name, 'result': result_out}, ensure_ascii=False)}\n\n"
                results.append((call.get("id", ""), name, result_out, call.get("arguments", {})))

            # 把「助手消息（含 tool_calls）」与「工具结果」回灌，进入下一轮反思
            messages.append({
                "role": "assistant",
                "content": assistant_text,
                "tool_calls": [
                    {
                        "id": cid,
                        "type": "function",
                        "function": {
                            "name": cname,
                            "arguments": json.dumps(_parse_tool_arguments(args), ensure_ascii=False),
                        },
                    }
                    for (cid, cname, _res, args) in results
                ],
            })
            for cid, cname, res, _args in results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": cid,
                    "content": json.dumps(res, ensure_ascii=False),
                })
        else:
            # 达到最大轮次仍有未处理的工具调用：强制做一次无工具的最终回答
            assistant_text = ""
            try:
                for item2 in llm_client.stream_llm(messages):
                    if isinstance(item2, str):
                        assistant_text += item2
                        yield f"data: {json.dumps({'type': 'text', 'content': item2}, ensure_ascii=False)}\n\n"
            except LLMUnavailableError as exc:
                yield sse_error(f"LLM 服务不可用：{exc}")
            final_answer_text = assistant_text

        # RAG 引用溯源：只在 LLM 最终答案中实际标注 [n] 的来源才回传给前端，
        # 避免把检索 top-k 全部展示造成的“乱引用”。
        cited_sources = _filter_cited_sources(final_answer_text, rag_sources_payload)
        yield f"data: {json.dumps({'type': 'rag_sources', 'sources': cited_sources, 'mode': rag_mode, 'enabled': req.rag_enabled}, ensure_ascii=False)}\n\n"
        yield f"data: {SSE_DONE}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = ["router"]
