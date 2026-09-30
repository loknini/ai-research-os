"""聊天工具循环保护与模型协议痕迹过滤。

模型偶尔会把 ``<tool_call>`` 协议当成普通文本输出，或者在已经取得结果后
继续重复调用同一工具。本模块集中处理这两类边界，避免原始协议进入 SSE/会话
正文，也避免一次回答产生无上限的外部请求。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import re
from typing import Any, Mapping, Optional


_PROTOCOL_MARKERS = (
    ("<tool_call", "</tool_call>"),
    ("<function=", "</function>"),
    ("<function>", "</function>"),
    ("<function ", "</function>"),
    ("<parameter=", "</parameter>"),
    ("<parameter>", "</parameter>"),
    ("<parameter ", "</parameter>"),
)
_TOOL_BLOCK_RE = re.compile(
    r"<tool_call\b[^>]*>[\s\S]*?(?:</tool_call\s*>|$)",
    re.IGNORECASE,
)
_FUNCTION_BLOCK_RE = re.compile(
    r"<function(?:\b|=)[^>]*>[\s\S]*?(?:</function\s*>|$)",
    re.IGNORECASE,
)
_PROTOCOL_TAG_RE = re.compile(
    r"</?(?:tool_call\b|function(?:\b|=)|parameter(?:\b|=))[^>]*>",
    re.IGNORECASE,
)


def strip_tool_call_traces(content: str) -> str:
    """从完整文本中移除模型误输出的工具协议，不保留调试副本。"""
    if not content:
        return content
    clean = _TOOL_BLOCK_RE.sub("", content)
    clean = _FUNCTION_BLOCK_RE.sub("", clean)
    clean = _PROTOCOL_TAG_RE.sub("", clean)
    return re.sub(r"\n{3,}", "\n\n", clean).strip()


def _suffix_prefix_length(value: str, marker: str) -> int:
    """返回 value 末尾与 marker 开头相同的最长长度，供跨分块识别标签。"""
    lower = value.lower()
    for size in range(min(len(value), len(marker) - 1), 0, -1):
        if lower.endswith(marker[:size]):
            return size
    return 0


class ToolTraceStreamFilter:
    """跨 SSE 分块过滤 ``<tool_call>...</tool_call>`` 协议块。

    过滤器只暂存可能组成标签的短后缀，普通自然语言仍会逐块输出，不会退化成
    等待整段回答完成后一次性显示。
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._inside_trace = False
        self._close_marker = ""
        self.removed_trace = False

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        self._buffer += chunk
        output: list[str] = []

        while self._buffer:
            lower = self._buffer.lower()
            if self._inside_trace:
                close_at = lower.find(self._close_marker)
                if close_at >= 0:
                    self._buffer = self._buffer[close_at + len(self._close_marker):]
                    self._inside_trace = False
                    self._close_marker = ""
                    continue
                keep = _suffix_prefix_length(self._buffer, self._close_marker)
                self._buffer = self._buffer[-keep:] if keep else ""
                return "".join(output)

            candidates = [
                (lower.find(open_marker), open_marker, close_marker)
                for open_marker, close_marker in _PROTOCOL_MARKERS
                if lower.find(open_marker) >= 0
            ]
            if candidates:
                open_at, open_marker, close_marker = min(candidates, key=lambda item: item[0])
                output.append(self._buffer[:open_at])
                self._buffer = self._buffer[open_at + len(open_marker):]
                self._inside_trace = True
                self._close_marker = close_marker
                self.removed_trace = True
                continue

            keep = max(
                _suffix_prefix_length(self._buffer, open_marker)
                for open_marker, _close_marker in _PROTOCOL_MARKERS
            )
            if keep:
                output.append(self._buffer[:-keep])
                self._buffer = self._buffer[-keep:]
            else:
                output.append(self._buffer)
                self._buffer = ""
            return "".join(output)

        return "".join(output)

    def finish(self) -> str:
        """结束流并返回安全尾部；未闭合的工具块整体丢弃。"""
        if self._inside_trace:
            self._buffer = ""
            self._inside_trace = False
            self._close_marker = ""
            return ""
        tail = self._buffer
        self._buffer = ""
        return strip_tool_call_traces(tail)


@dataclass(frozen=True)
class ToolCallDecision:
    allowed: bool
    reason: Optional[str] = None


class ToolCallGuard:
    """为单次聊天请求限制工具总量、单工具数量、重复调用和连续失败。"""

    def __init__(
        self,
        *,
        total_limit: int = 8,
        consecutive_failure_limit: int = 3,
        per_tool_limits: Optional[Mapping[str, int]] = None,
    ) -> None:
        self.total_limit = total_limit
        self.consecutive_failure_limit = consecutive_failure_limit
        self.per_tool_limits = dict(per_tool_limits or {"web_search": 4})
        self.total_calls = 0
        self.consecutive_failures = 0
        self._seen: set[str] = set()
        self._counts: Counter[str] = Counter()

    @staticmethod
    def _signature(name: str, parameters: Mapping[str, Any]) -> str:
        serialized = json.dumps(parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"{name}:{serialized}"

    def inspect(self, name: str, parameters: Mapping[str, Any]) -> ToolCallDecision:
        """判断调用是否可执行；获准的调用会立即计入预算和去重集合。"""
        signature = self._signature(name, parameters)
        if signature in self._seen:
            return ToolCallDecision(False, f"检测到重复工具调用：{name} 参数与此前完全相同")
        if self.total_calls >= self.total_limit:
            return ToolCallDecision(False, f"工具调用总量已达到安全上限 {self.total_limit}")
        tool_limit = self.per_tool_limits.get(name)
        if tool_limit is not None and self._counts[name] >= tool_limit:
            return ToolCallDecision(False, f"{name} 调用次数已达到安全上限 {tool_limit}")

        self._seen.add(signature)
        self._counts[name] += 1
        self.total_calls += 1
        return ToolCallDecision(True)

    def record_result(self, result: Any) -> Optional[str]:
        """记录执行结果；连续失败达到阈值时返回强制收尾原因。"""
        succeeded = not isinstance(result, dict) or result.get("success", True) is not False
        self.consecutive_failures = 0 if succeeded else self.consecutive_failures + 1
        if self.consecutive_failures >= self.consecutive_failure_limit:
            return f"工具已连续失败 {self.consecutive_failures} 次"
        return None


def blocked_tool_result(reason: str) -> dict[str, Any]:
    """生成可安全回灌给模型、且明确禁止重试的工具结果。"""
    return {
        "success": False,
        "status": "blocked",
        "error": reason,
        "retryable": False,
        "instruction": "停止调用工具，基于已经取得的结果直接生成自然语言回答。",
    }


__all__ = [
    "ToolCallDecision",
    "ToolCallGuard",
    "ToolTraceStreamFilter",
    "blocked_tool_result",
    "strip_tool_call_traces",
]
