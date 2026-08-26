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
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.server import health  # noqa: E402
from backend.server.llm import LLMClient  # noqa: E402


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

    # 端点处理函数使用全局 client；打桩探测本身并清空 TTL 缓存，确保不触网。
    health._reach_cache.update(ts=0.0, val=False)
    with patch.object(health.llm_client, "_reachable", return_value=True):
        payload = asyncio.run(health.llm_status())
    assert payload["success"] is True
    assert payload["reachable"] is True

    print("ALL_LLM_STATUS_QA_PASS")


if __name__ == "__main__":
    main()
