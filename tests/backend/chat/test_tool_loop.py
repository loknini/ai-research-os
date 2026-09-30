"""Chat 工具循环与输出协议的原生 pytest 回归。"""
from __future__ import annotations

import importlib
import json

import pytest


pytestmark = [pytest.mark.fast, pytest.mark.core]


def _sse_events(body: str) -> list[dict]:
    events: list[dict] = []
    for line in body.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        events.append(json.loads(line[6:]))
    return events


def test_stream_filter_handles_split_protocol() -> None:
    from backend.server.services.chat_guard import ToolTraceStreamFilter, strip_tool_call_traces

    stream_filter = ToolTraceStreamFilter()
    chunks = [
        "正常前缀<tool_",
        "call><function=web_search><parameter=query>secret",
        "</parameter></function></tool_call>正常后缀",
    ]
    clean = "".join(stream_filter.feed(chunk) for chunk in chunks) + stream_filter.finish()
    assert clean == "正常前缀正常后缀"
    assert stream_filter.removed_trace is True
    assert strip_tool_call_traces(
        "正文\n<tool_call><function=web_search>私密参数</function></tool_call>\n结尾"
    ) == "正文\n\n结尾"
    assert strip_tool_call_traces("正文<tool_call>未闭合") == "正文"
    assert strip_tool_call_traces("保留 <functionality> 普通标签") == "保留 <functionality> 普通标签"


def test_call_guard_limits_duplicates_and_failures() -> None:
    from backend.server.services.chat_guard import ToolCallGuard

    guard = ToolCallGuard(
        total_limit=3,
        consecutive_failure_limit=2,
        per_tool_limits={"web_search": 2},
    )
    assert guard.inspect("web_search", {"query": "a"}).allowed is True
    duplicate = guard.inspect("web_search", {"query": "a"})
    assert duplicate.allowed is False
    assert "重复" in (duplicate.reason or "")
    assert guard.record_result({"success": False}) is None
    assert guard.inspect("web_search", {"query": "b"}).allowed is True
    assert "连续失败" in (guard.record_result({"success": False}) or "")
    limited = guard.inspect("web_search", {"query": "c"})
    assert limited.allowed is False
    assert "安全上限" in (limited.reason or "")


def test_endpoint_guard_and_finalization(app_client, monkeypatch: pytest.MonkeyPatch) -> None:
    chat_router = importlib.import_module("backend.server.routers.chat")
    executed: list[tuple[str, dict]] = []
    invocations: list[dict] = []

    def fake_stream(messages, *, tools=None, **_kwargs):
        invocations.append({"messages": messages, "tools": tools})
        if tools is not None:
            yield {
                "tool_calls": [
                    {
                        "id": f"call-{index}",
                        "name": "web_search",
                        "arguments": {"query": f"query-{index}"},
                    }
                    for index in range(5)
                ]
            }
            return
        yield "已整理已有资料。\n<tool_"
        yield "call><function=web_search><parameter=query>不应泄露"
        yield "</parameter></function></tool_call>\n回答完成。"

    def fake_execute(name, params, *, space_id):
        executed.append((name, params))
        return {"success": True, "results": [{"title": params["query"]}]}

    monkeypatch.setattr(chat_router.llm_client, "stream_llm", fake_stream)
    monkeypatch.setattr(chat_router, "execute_tool", fake_execute)
    response = app_client.post(
        "/api/chat/completions/stream",
        headers={"X-Space-Key": "qa-chat-guard"},
        json={"messages": [{"role": "user", "content": "查资料"}]},
    )

    assert response.status_code == 200, response.text
    events = _sse_events(response.text)
    text = "".join(event.get("content", "") for event in events if event.get("type") == "text")
    starts = [event for event in events if event.get("type") == "tool_start"]
    results = [event for event in events if event.get("type") == "tool_result"]
    assert len(executed) == 4
    assert len(starts) == 4 and len(results) == 4
    assert text == "已整理已有资料。\n\n回答完成。"
    assert "tool_call" not in response.text and "不应泄露" not in response.text
    assert len(invocations) == 2 and invocations[1]["tools"] is None
    blocked_results = [
        message
        for message in invocations[1]["messages"]
        if message.get("role") == "tool" and '"status": "blocked"' in message.get("content", "")
    ]
    assert len(blocked_results) == 1
    assert "禁止输出 <tool_call>" in invocations[1]["messages"][0]["content"]


def test_web_search_contract(run_isolated_case) -> None:
    run_isolated_case("tests.backend._cases.chat.case_web_search")
