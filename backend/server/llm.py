"""零额外依赖的 OpenAI 兼容 LLM 客户端。

本项目不使用 ``openai`` SDK，客户端基于 Python 标准库 ``urllib`` 实现，并沿用
``scripts/chat_agent_stream.py`` 的 SSE 解析约定。

接口约定：
  * ``call_llm(...)`` -> ``str | None``；失败时返回 ``None``，由调用方降级；
  * ``stream_llm(...)`` -> ``Generator[str | dict]``；逐段产生文本、可选的
    ``{"usage": ...}``，以及至多一组 ``{"tool_calls": ...}``，连接失败时抛出
    ``LLMUnavailableError``；
  * ``is_available()`` -> ``bool``。

请求发送到 ``{LLM_BASE_URL}{LLM_HTTP_PATH}``，默认路径为
``/chat/completions``，并携带 ``Authorization: Bearer {LLM_API_KEY}``。
Base URL 应包含 OpenAI 兼容接口常用的 ``/v1`` 前缀。
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Generator, List, Optional

from .core import config
from .utils import mask_key


class LLMUnavailableError(Exception):
    """流式调用无法连接已配置的 LLM 端点时抛出。"""


class LLMClient:
    """使用 urllib 实现的 OpenAI 兼容 LLM 客户端，不依赖 SDK。"""

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
    # 属性
    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        """是否同时配置了 API Key 和 Base URL。"""
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
    # 内部辅助方法
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
    # 公共 API
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
        """非流式调用；成功时返回文本，任何失败均返回 ``None``。"""
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
            # 连接、解析或 HTTP 错误均按不可用结果优雅降级。
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
        """支持 OpenAI 原生 function calling 的流式调用。

        逐段产生文本；服务支持流式用量时可能产生 ``{"usage": ...}``。SSE 结束后，
        仅当模型请求工具时才至多产生一次 ``{"tool_calls": [...]}``；其中累计的参数
        会尝试解析为 JSON，失败则保留原字符串。连接失败时抛出
        ``LLMUnavailableError``。未传 ``tools`` 时仍只产生文本增量。
        """
        eff = self._eff()
        payload = self._build_payload(messages, stream=True, model=model,
                                       temperature=temperature, max_tokens=max_tokens,
                                       tools=tools)
        timeout = timeout or eff.get("timeout")
        # OpenAI 兼容服务仅在显式请求时返回精确的流式用量。旧服务可能拒绝该选项；
        # 遇到这种情况先移除该选项重试一次，再向上报告可用性错误。
        payload["stream_options"] = {"include_usage": True}

        def open_stream(request_payload: Dict[str, Any]):
            data = json.dumps(request_payload).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint, data=data, headers=self._headers(), method="POST"
            )
            return urllib.request.urlopen(req, timeout=timeout)
        # 跨 SSE 增量累计函数调用片段，并按工具调用索引归并；
        # OpenAI 兼容接口会分段返回这些字段。
        tool_acc: Dict[int, Dict[str, Any]] = {}
        latest_usage: Optional[Dict[str, int]] = None
        try:
            try:
                response = open_stream(payload)
            except urllib.error.HTTPError as exc:
                if exc.code not in (400, 422):
                    raise
                fallback_payload = dict(payload)
                fallback_payload.pop("stream_options", None)
                response = open_stream(fallback_payload)

            with response as resp:
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
                    usage = obj.get("usage")
                    if isinstance(usage, dict):
                        prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
                        completion_tokens = usage.get(
                            "completion_tokens", usage.get("output_tokens", 0)
                        )
                        try:
                            prompt_tokens = int(prompt_tokens or 0)
                            completion_tokens = int(completion_tokens or 0)
                            total_tokens = int(
                                usage.get("total_tokens")
                                or prompt_tokens + completion_tokens
                            )
                        except (TypeError, ValueError):
                            prompt_tokens = completion_tokens = total_tokens = 0
                        if total_tokens > 0:
                            # 某些 OpenAI 兼容服务会在多个分片中重复发送累计 usage。
                            # 这里只保留本次请求的最后一份快照，避免前端把同一请求重复相加。
                            latest_usage = {
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "total_tokens": total_tokens,
                            }
                    choices = obj.get("choices") or []
                    delta = choices[0].get("delta", {}) if choices else {}
                    content = delta.get("content")
                    if content:
                        yield content
                    # 累计原生 function-calling 工具调用片段。
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

        if latest_usage:
            yield {"usage": latest_usage}

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
    # 向量嵌入（OpenAI 兼容的 /v1/embeddings）
    # ------------------------------------------------------------------
    @property
    def embedding_endpoint(self) -> str:
        """嵌入端点 ``{base}/embeddings``；base 已包含 ``/v1``。"""
        eff = self._eff()
        base = (eff.get("baseUrl") or "").rstrip("/")
        return f"{base}/embeddings"

    @property
    def embedding_model(self) -> str:
        """嵌入模型名；未配置时回退为聊天模型名。"""
        eff = self._eff()
        return (eff.get("embedModel") or "").strip() or (eff.get("model") or "")

    def embed(
        self,
        texts: List[str],
        *,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Optional[List[List[float]]]:
        """OpenAI 兼容的非流式嵌入调用。

        把字符串列表作为 ``input`` 发送到 ``{base}/embeddings``，并按原顺序返回
        浮点向量列表；任何失败均返回 ``None``，供调用方回退到关键词检索。
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

    # ------------------------------------------------------------------
    # 带回退的向量嵌入（API → 本地模型 → None）
    # ------------------------------------------------------------------
    def embed_with_fallback(
        self,
        texts: List[str],
        *,
        model: Optional[str] = None,
    ) -> Optional[List[List[float]]]:
        """三层降级嵌入：根据 EMBED_PROVIDER 配置决定优先策略。

        * ``"local"``：优先本地 → 失败回退 API
        * ``"api"``（默认）：优先 API → 失败回退本地（如果已配置）
        * 两者都失败：返回 ``None``（调用方降级关键词检索）
        """
        if not texts:
            return []
        eff = self._eff()
        provider = (eff.get("embedProvider") or "").strip() or "api"

        if provider == "local":
            vecs = self._try_local_embed(texts, eff)
            if vecs is not None:
                return vecs
            return self.embed(texts, model=model)
        else:
            vecs = self.embed(texts, model=model)
            if vecs is not None:
                return vecs
            return self._try_local_embed(texts, eff)

    def embed_exact(
        self,
        texts: List[str],
        *,
        provider: str,
        model: str,
        revision: str = "",
        is_query: bool = False,
        query_instruction: str = "",
    ) -> Optional[List[List[float]]]:
        """只使用指定嵌入空间；失败返回 None，绝不偷偷切换模型。"""
        if not texts:
            return []
        if provider == "local":
            eff = self._eff()
            try:
                return self._try_local_embed(
                    texts, eff, model_path=model, revision=revision,
                    is_query=is_query, query_instruction=query_instruction)
            except TypeError:
                # 兼容测试/扩展里仍按旧二参签名 monkeypatch 的实现。
                return self._try_local_embed(texts, eff)
        if provider == "api":
            return self.embed(texts, model=model)
        return None

    def _try_local_embed(
        self, texts: List[str], eff: Dict[str, Any], *,
        model_path: str = "", revision: str = "", is_query: bool = False,
        query_instruction: str = "",
    ) -> Optional[List[List[float]]]:
        """尝试本地嵌入（provider=local 且模型已配置时）。"""
        model_path = model_path or (eff.get("embedLocalModel") or "").strip()
        revision = revision or (eff.get("embedLocalRevision") or "").strip()
        if not model_path:
            return None
        try:
            from .rag.local_embed import get_local_embedder
            embedder = get_local_embedder()
            if not embedder.load(model_path, revision=revision):
                return None
            return embedder.embed(
                texts, is_query=is_query,
                instruction=query_instruction or (eff.get("embedQueryInstruction") or ""))
        except Exception:
            return None

    @property
    def embedding_provider(self) -> str:
        """当前生效的嵌入提供者（"api" / "local"）。"""
        eff = self._eff()
        return (eff.get("embedProvider") or "").strip() or "api"

    def is_available(self) -> bool:
        """LLM 是否已配置且网络可达。"""
        if not self.configured:
            return False
        return self._reachable()

    def _reachable(self) -> bool:
        """对已配置 Base URL 执行轻量 TCP 可达性检查。"""
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
        """供 ``/api/llm/status`` 与 ``/api/healthz`` 使用的结构化状态。"""
        eff = self._eff()
        return {
            "configured": self.configured,
            "reachable": self._reachable(),
            "baseUrl": eff.get("baseUrl") or "",
            "model": eff.get("model") or "",
            "apiKeyMasked": mask_key(eff.get("apiKey") or ""),
        }

# 应用共享的客户端单例。
llm_client = LLMClient()


__all__ = ["LLMClient", "LLMUnavailableError", "llm_client"]
