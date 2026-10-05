"""LLM 状态与可选依赖的回归。"""
from __future__ import annotations

import asyncio
import io
import json
import os
import urllib.error
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _settings(base_url: str = "https://example.test/v1", api_key: str = "secret"):
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


@pytest.mark.fast
@pytest.mark.core
def test_llm_status_and_usage_are_offline_safe() -> None:
    from backend.server.core import health
    from backend.server.llm import LLMClient

    with patch(
        "backend.server.llm.config.get_effective_llm_settings",
        side_effect=RuntimeError("isolated pytest settings"),
    ):
        client = LLMClient(_settings())
        assert callable(getattr(client, "_reachable", None))

        fake_socket = MagicMock()
        with patch("backend.server.llm.socket.create_connection", return_value=fake_socket) as connect:
            assert client._reachable() is True
            assert client.is_available() is True
            assert client.status()["reachable"] is True
            connect.assert_called_with(("example.test", 443), timeout=3)

        assert LLMClient(_settings(base_url="not-a-url"))._reachable() is False
        with patch("backend.server.llm.socket.create_connection", side_effect=OSError("offline")):
            assert client._reachable() is False

        requests = []

        class FakeStream:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                return iter(
                    [
                        b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
                        b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n',
                        b'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3,"total_tokens":15}}\n',
                        b"data: [DONE]\n",
                    ]
                )

        def fake_urlopen(request, timeout=None):
            del timeout
            requests.append(json.loads(request.data.decode("utf-8")))
            if len(requests) == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    400,
                    "unsupported",
                    {},
                    io.BytesIO(),
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

    health._reach_cache.update(ts=0.0, val=False)
    with patch.object(health.llm_client, "_reachable", return_value=True):
        payload = asyncio.run(health.llm_status())
    assert payload["success"] is True
    assert payload["reachable"] is True


def test_optional_dependency_fallbacks(run_isolated_case) -> None:
    run_isolated_case("tests.backend._cases.infrastructure.case_optional_deps")


@pytest.mark.fast
@pytest.mark.core
def test_process_liveness_probe_never_signals_on_windows() -> None:
    from scripts import process_utils

    if os.name != "nt":
        pytest.skip("Windows-specific regression")

    with patch("scripts.process_utils.os.kill") as kill:
        assert process_utils.pid_is_running(os.getpid()) is True
        assert process_utils.pid_is_running(999_999_999) is False
        kill.assert_not_called()
