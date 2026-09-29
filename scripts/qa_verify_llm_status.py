#!/usr/bin/env python3
"""LLM 可达性与状态端点回归测试（不触网、不写库）。

覆盖曾因 ``_reachable`` 缩进丢失导致的正确性回归：
  * LLMClient 实际暴露 ``_reachable()``；
  * 合法 URL 使用轻量 TCP 探测，异常/非法 URL 返回 False；
  * ``is_available()`` 与 ``status()`` 可正常调用；
  * ``/api/llm/status`` 的处理函数不再抛 AttributeError。
"""
from __future__ import annotations

import asyncio
import io
import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.server.core import health
from backend.server.llm import LLMClient


def make_settings(base_url: str = "https://example.test/v1", api_key: str = "secret"):
    return SimpleNamespace(
        llm_base_url=base_url,
        llm_api_key=api_key,
        llm_model="test-model",
        llm_temperature=0.7,
        llm_max_tokens=100,
        llm_timeout=1,
        llm_http_path="/chat/completions",
        llm_embed_model="test-embed",
    )


def main() -> None:
    # 隔离本机 .env/数据库中的真实配置，强制使用测试 settings。
    with patch(
        "backend.server.llm.config.get_effective_llm_settings",
        side_effect=RuntimeError("isolated QA settings"),
    ):
        client = LLMClient(make_settings())
        assert callable(getattr(client, "_reachable", None))

        fake_socket = MagicMock()
        with patch("backend.server.llm.socket.create_connection", return_value=fake_socket) as connect:
            assert client._reachable() is True
            assert client.is_available() is True
            assert client.status()["reachable"] is True
            connect.assert_called_with(("example.test", 443), timeout=3)

        invalid = LLMClient(make_settings(base_url="not-a-url"))
        assert invalid._reachable() is False

        with patch("backend.server.llm.socket.create_connection", side_effect=OSError("offline")):
            assert client._reachable() is False

        # 精确 usage：优先请求 stream_options；旧供应商返回 400 时自动回退，
        # 且仍能解析文本与最终 token 用量。
        requests = []

        class FakeStream:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                return iter([
                    b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
                    b'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3,"total_tokens":15}}\n',
                    b'data: [DONE]\n',
                ])

        def fake_urlopen(request, timeout=None):
            del timeout
            requests.append(json.loads(request.data.decode("utf-8")))
            if len(requests) == 1:
                raise urllib.error.HTTPError(
                    request.full_url, 400, "unsupported", {}, io.BytesIO()
                )
            return FakeStream()

        with patch("backend.server.llm.urllib.request.urlopen", side_effect=fake_urlopen):
            items = list(client.stream_llm([{"role": "user", "content": "hi"}]))
        assert items == [
            "ok",
            {"usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}},
        ]
        assert "stream_options" in requests[0]
        assert "stream_options" not in requests[1]

    # 端点处理函数使用全局 client；打桩探测本身并清空 TTL 缓存，确保不触网。
    health._reach_cache.update(ts=0.0, val=False)
    with patch.object(health.llm_client, "_reachable", return_value=True):
        payload = asyncio.run(health.llm_status())
    assert payload["success"] is True
    assert payload["reachable"] is True

    print("ALL_LLM_STATUS_QA_PASS")


if __name__ == "__main__":
    main()
