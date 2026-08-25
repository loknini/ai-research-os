"""共享上下文管理：token 估算 / 历史摘要 / 消息压缩。

从 ``backend/server/routers/chat.py`` 抽出，供 Chat 与多 Agent 角色管线共用
（避免两处各写一份压缩逻辑）。

压缩策略
--------
当消息序列的 token 估算超过预算时，把「保留末尾 ``keep_last`` 条消息之前」的
历史用 LLM 压缩成单条 system 摘要消息。切分点选在最近一个 **user** 边界上，
保证不切断 assistant(tool_calls) 与其 tool 结果之间的配对。

默认预算与保留条数可分别用 ``CONTEXT_TOKEN_LIMIT`` / ``CONTEXT_KEEP_LAST_MESSAGES``
环境变量覆盖（Agent 管线另有 ``AGENT_CONTEXT_TOKEN_LIMIT`` / ``AGENT_CONTEXT_KEEP_LAST``）。
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

from .llm import llm_client

# 默认上下文预算（token 估算）与保留条数。
CONTEXT_TOKEN_LIMIT = int(os.environ.get("CONTEXT_TOKEN_LIMIT", "16000"))
KEEP_LAST_MESSAGES = int(os.environ.get("CONTEXT_KEEP_LAST_MESSAGES", "6"))


def estimate_tokens(messages: List[Dict]) -> int:
    """粗略 token 估算：CJK 字符≈1 token，其它非空白字符≈0.25 token。"""
    total = 0
    for m in messages:
        c = m.get("content", "")
        if not isinstance(c, str):
            try:
                c = json.dumps(c, ensure_ascii=False)
            except Exception:
                c = str(c)
        for ch in c:
            if "一" <= ch <= "鿿" or "぀" <= ch <= "ヿ" or "가" <= ch <= "힯":
                total += 1
            elif not ch.isspace():
                total += 0.25
    return int(total)


def summarize_history(prefix_messages: List[Dict]) -> Optional[str]:
    """用 LLM 把一段历史压缩成摘要；失败返回 ``None``（调用方跳过压缩）。"""
    text = "\n\n".join(
        f"[{m.get('role', 'user')}]: {m.get('content', '')}" for m in prefix_messages
    )
    if not text.strip():
        return None
    sys_prompt = (
        "你是对话历史压缩器。请保留对后续对话有用的事实、用户偏好、已完成操作与待办，"
        "用简短要点输出（中文），不要编造。若信息不足，输出『（无重要历史）』。"
    )
    try:
        out = llm_client.call_llm(
            [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
            max_tokens=800,
        )
    except Exception:
        return None
    return out


def compact_messages(
    messages: List[Dict],
    limit: int = CONTEXT_TOKEN_LIMIT,
    keep_last: int = KEEP_LAST_MESSAGES,
) -> Tuple[List[Dict], bool]:
    """若历史超阈值，把中间部分摘要为单条 system 消息。

    返回 ``(new_messages, compressed)``；找不到干净切分点或摘要失败时原样返回
    ``(messages, False)``，绝不破坏 tool 配对。
    """
    if len(messages) <= 2 + keep_last:
        return messages, False
    if estimate_tokens(messages) <= limit:
        return messages, False

    split = len(messages) - keep_last
    while split > 1 and messages[split].get("role") != "user":
        split -= 1
    if split <= 1:
        return messages, False  # 找不到干净边界，跳过压缩

    prefix = messages[1:split]
    summary = summarize_history(prefix)
    if not summary:
        return messages, False
    new_messages = [
        messages[0],
        {"role": "system", "content": "[对话历史摘要]\n" + summary},
    ] + messages[split:]
    return new_messages, True


__all__ = [
    "CONTEXT_TOKEN_LIMIT",
    "KEEP_LAST_MESSAGES",
    "estimate_tokens",
    "summarize_history",
    "compact_messages",
]
