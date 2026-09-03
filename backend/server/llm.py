"""LLM client (OpenAI-compatible, zero extra dependencies).

Implements the agreed decision: **do not** use the ``openai`` SDK.  The client is
built with the Python standard library ``urllib`` (mirroring the existing
``scripts/agent_service.py`` ``call_llm`` and ``scripts/chat_agent_stream.py`` SSE
parsing logic) so there are no new third-party dependencies.

Contract:
  * ``call_llm(...)``  -> ``str | None``  (returns ``None`` on any failure; callers degrade)
  * ``stream_llm(...)`` -> ``Generator[str | dict]`` (yields ``str`` text deltas;
    after the stream ends it yields **at most one** ``dict`` with key
    ``"tool_calls"`` when the model requested function/tool calls; raises
    ``LLMUnavailableError`` on connection failure)
  * ``is_available()`` -> ``bool``

Requests are sent to ``{LLM_BASE_URL}{LLM_HTTP_PATH}`` (default
``/chat/completions``) with ``Authorization: Bearer {LLM_API_KEY}``.
Base URL should include the ``/v1`` prefix (OpenAI SDK convention).
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Generator, List, Optional

from . import config
from .utils import mask_key


class LLMUnavailableError(Exception):
    """Raised when the configured LLM endpoint cannot be reached (streaming)."""


class LLMClient:
    """OpenAI-compatible LLM client implemented with urllib (no SDK)."""

    def __init__(self, settings: Any = None) -> None:
        self.settings = settings or config.settings

    def _eff(self) -> Dict[str, Any]:
        """当前生效配置（DB TTL 缓存，多 worker 可见）。"""
        try:
            return config.get_effective_llm_settings()
        except Exception:
            return {
                "baseUrl": self.settings.llm_base_url,
                "apiKey": self.settings.llm_api_key,
                "model": self.settings.llm_model,
                "temperature": self.settings.llm_temperature,
                "maxTokens": self.settings.llm_max_tokens,
                "timeout": self.settings.llm_timeout,
                "httpPath": self.settings.llm_http_path,
                "embedModel": self.settings.llm_embed_model,
            }

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        """Whether an API key + base URL are present."""
        eff = self._eff()
        key = (eff.get("apiKey") or "").strip()
        base = (eff.get("baseUrl") or "").strip()
        return bool(key) and bool(base)

    @property
    def endpoint(self) -> str:
        eff = self._eff()
        base = (eff.get("baseUrl") or "").rstrip("/")
        path = eff.get("httpPath") or "/chat/completions"
        return f"{base}{path}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        eff = self._eff()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {eff.get('apiKey') or ''}",
        }

    def _build_payload(
        self,
        messages: List[Dict[str, str]],
        stream: bool,
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        eff = self._eff()
        payload: Dict[str, Any] = {
            "model": model or eff.get("model"),
            "messages": messages,
            "temperature": temperature if temperature is not None else eff.get("temperature"),
            "max_tokens": max_tokens if max_tokens is not None else eff.get("maxTokens"),
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def call_llm(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> Optional[str]:
        """Non-streaming call. Returns the text, or ``None`` on any failure."""
        eff = self._eff()
        payload = self._build_payload(messages, stream=False, model=model,
                                       temperature=temperature, max_tokens=max_tokens)
        timeout = timeout or eff.get("timeout")
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint, data=data, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
        except Exception:
            # Any connection / parse / HTTP error -> degrade gracefully.
            return None

    def stream_llm(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Generator[Any, None, None]:
        """Streaming call with native OpenAI function calling support.

        Contract:
          * Yields ``str`` text deltas as they arrive.
          * After the SSE stream ends, yields **at most one** ``dict`` with the
            key ``"tool_calls"`` (only when the model requested tool calls).
            Each entry has the shape
            ``{"id": str, "name": str, "arguments": <parsed json object>}``
            where ``arguments`` is the result of ``json.loads`` on the
            accumulated argument string (falls back to the raw string on error).
          * Raises ``LLMUnavailableError`` on connection failure.

        When ``tools`` is falsy the behaviour is unchanged from before
        (text deltas only).
        """
        eff = self._eff()
        payload = self._build_payload(messages, stream=True, model=model,
                                       temperature=temperature, max_tokens=max_tokens,
                                       tools=tools)
        timeout = timeout or eff.get("timeout")
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint, data=data, headers=self._headers(), method="POST"
        )
        # Accumulate incremental function-call fragments across SSE deltas.
        # Keyed by the tool-call index (OpenAI emits them incrementally).
        tool_acc: Dict[int, Dict[str, Any]] = {}
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8").strip()
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    delta = obj.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
                    # Accumulate native function-calling tool calls.
                    for tc in (delta.get("tool_calls") or []):
                        idx = tc.get("index", 0)
                        slot = tool_acc.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ConnectionError) as exc:
            raise LLMUnavailableError(str(exc)) from exc

        if tool_acc:
            calls = []
            for idx in sorted(tool_acc.keys()):
                slot = tool_acc[idx]
                raw_args = slot["arguments"]
                try:
                    parsed_args: Any = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    parsed_args = raw_args
                calls.append({
                    "id": slot["id"],
                    "name": slot["name"],
                    "arguments": parsed_args,
                })
            yield {"tool_calls": calls}

    # ------------------------------------------------------------------
    # Embeddings (OpenAI-compatible /v1/embeddings)
    # ------------------------------------------------------------------
    @property
    def embedding_endpoint(self) -> str:
        """Embeddings endpoint: ``{base}/embeddings`` (base already has /v1)."""
        eff = self._eff()
        base = (eff.get("baseUrl") or "").rstrip("/")
        return f"{base}/embeddings"

    @property
    def embedding_model(self) -> str:
        """Embedding model name; falls back to the chat model when unset."""
        eff = self._eff()
        return (eff.get("embedModel") or "").strip() or (eff.get("model") or "")

    def embed(
        self,
        texts: List[str],
        *,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Optional[List[List[float]]]:
        """Non-streaming embeddings call (OpenAI-compatible).

        Sends ``input`` as a list of strings to ``{base}/embeddings`` and
        returns a list of float vectors in the same order. Returns ``None`` on
        any failure so callers can degrade to keyword retrieval.
        """
        if not texts:
            return []
        eff = self._eff()
        model = model or self.embedding_model
        if not self.configured or not model:
            return None
        payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
        timeout = timeout or eff.get("timeout")
        req = urllib.request.Request(
            self.embedding_endpoint, data=payload, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            data = result.get("data") or []
            vecs = {int(d.get("index", i)): d.get("embedding") for i, d in enumerate(data)}
            ordered = [vecs[i] for i in range(len(data)) if vecs.get(i)]
            return ordered if ordered else None
        except Exception:
            return None

    def is_available(self) -> bool:
        """Whether the LLM is configured *and* reachable."""
        if not self.configured:
            return False
        return self._reachable()

    def _reachable(self) -> bool:
        """Lightweight TCP reachability check for the configured base URL."""
        from urllib.parse import urlparse

        try:
            eff = self._eff()
            parsed = urlparse(eff.get("baseUrl") or "")
            host = parsed.hostname
            if not host:
                return False
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            with socket.create_connection((host, port), timeout=3):
                return True
        except Exception:
            return False

    def status(self) -> Dict[str, Any]:
        """Structured status used by ``/api/llm/status`` and ``/api/healthz``."""
        eff = self._eff()
        return {
            "configured": self.configured,
            "reachable": self._reachable(),
            "baseUrl": eff.get("baseUrl") or "",
            "model": eff.get("model") or "",
            "apiKeyMasked": mask_key(eff.get("apiKey") or ""),
        }

# Singleton used across the app.
llm_client = LLMClient()


__all__ = ["LLMClient", "LLMUnavailableError", "llm_client"]
