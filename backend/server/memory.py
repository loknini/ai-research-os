"""持久记忆（Persistent Memory）—— 让 AI "越用越懂用户"。

设计参照 OpenClaw 的 ``AGENTS/SOUL/MEMORY`` 思路，但落地为可隔离的、按空间
（space_id）存储的长期记忆文件：

* 每个空间一份 ``data/memory/<space_id>.md``（人类可读的 Markdown）。
* 既可由用户/管理员在「设置 → 记忆」里直接编辑，也可由 LLM 从对话中自动提炼
  （``extract_facts`` / ``/api/memory/extract``），沉淀用户偏好、项目背景、待办等。
* ``memory_prompt(space_id)`` 在每次聊天时把记忆注入 system prompt，使助手自带
  长期上下文；``chat.py`` 负责调用它。

零第三方依赖（仅标准库 + 复用 ``config.DATA_DIR``）。线程安全（写操作加锁）。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional

from . import config

# 记忆目录：data/memory/<space_id>.md
_MEMORY_DIR = config.DATA_DIR / "memory"
_lock = threading.Lock()

# 单条记忆最大长度，防止单条无限膨胀
_MAX_ENTRY_CHARS = 4000
# 注入 system prompt 时的记忆上限（避免记忆本身把上下文撑爆）
_MAX_INJECT_CHARS = 2500


def _safe_name(space_id: str) -> str:
    """把空间标识规范成安全的文件名（替换路径分隔符）。"""
    return (space_id or "__default__").replace("/", "_").replace("\\", "_").replace("..", "_")


def _path(space_id: str) -> Path:
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return _MEMORY_DIR / f"{_safe_name(space_id)}.md"


def load_memory(space_id: str) -> str:
    """读取某空间的记忆全文（Markdown），不存在则返回空串。"""
    p = _path(space_id)
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def save_memory(space_id: str, text: str) -> bool:
    """整体覆盖某空间的记忆（用户手动编辑用）。"""
    p = _path(space_id)
    try:
        with _lock:
            p.write_text((text or "").strip(), encoding="utf-8")
        return True
    except Exception:
        return False


def append_memory(space_id: str, entry: str) -> bool:
    """追加一条记忆（自动加分隔）。返回是否写入成功。"""
    entry = (entry or "").strip()
    if not entry:
        return False
    if len(entry) > _MAX_ENTRY_CHARS:
        entry = entry[:_MAX_ENTRY_CHARS].rstrip() + "…"
    p = _path(space_id)
    try:
        with _lock:
            existing = p.read_text(encoding="utf-8").strip() if p.exists() else ""
            new = (existing + "\n\n" + entry) if existing else entry
            p.write_text(new, encoding="utf-8")
        return True
    except Exception:
        return False


def memory_prompt(space_id: str, max_chars: int = _MAX_INJECT_CHARS) -> str:
    """生成注入 system prompt 的记忆块；无记忆则返回空串。"""
    mem = load_memory(space_id)
    if not mem:
        return ""
    if len(mem) > max_chars:
        mem = mem[-max_chars:]
    return (
        "\n\n## 长期记忆（关于该用户 / 空间，越用越熟悉；请据此调整语气、偏好与默认行为）\n"
        + mem
    )


def extract_facts(messages: List[dict], space_id: str = "__default__") -> Optional[str]:
    """用 LLM 从一段对话中提炼可长期沉淀的事实（用户偏好 / 项目背景 / 待办）。

    返回提炼出的 Markdown 要点串；失败（LLM 不可达）返回 ``None``。
    调用方决定是否 ``append_memory``，本函数不落盘，保持纯函数语义。
    """
    try:
        from .llm import llm_client, LLMUnavailableError
    except Exception:
        return None

    dialogue_text = "\n\n".join(
        f"[{m.get('role', 'user')}]: {m.get('content', '')}" for m in messages if m.get("content")
    )
    if not dialogue_text.strip():
        return None

    sys_prompt = (
        "你负责把对话中值得长期记住的信息提炼成简洁的要点（中文，每条一行，以 - 开头）。"
        "只提取：用户明确表达的偏好/习惯、正在进行的项目背景、重要待办与截止时间、"
        "反复出现的术语或约定。不要记录一次性问答的细节，不要编造。"
        "若没有值得长期记住的内容，只回复空字符串。"
    )
    try:
        out = llm_client.call_llm(
            [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": dialogue_text},
            ],
            temperature=0.2,
            max_tokens=600,
        )
    except LLMUnavailableError:
        return None
    except Exception:
        return None
    if not out:
        return None
    return out.strip()


__all__ = [
    "load_memory",
    "save_memory",
    "append_memory",
    "memory_prompt",
    "extract_facts",
]
