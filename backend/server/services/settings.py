"""LLM、本地嵌入和集成配置的读取、保存与连接测试服务。

保存配置时同时热更新进程内 ``config.settings`` 单例并写入项目根 ``.env``，
因此当前 worker 立即生效，重启后也能恢复。``.env`` 写入采用 upsert：保留无关
行和注释，只替换或追加本服务管理的键。

本模块不声明 HTTP 路由；管理权限、路径和 HTTP 方法由 ``routers/settings.py``
负责。
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from ..core import config
from ..utils import mask_key

ENV_PATH: Path = config.PROJECT_ROOT / ".env"

# 本服务管理的配置键；顺序同时决定缺失键追加到 .env 时的排列顺序。
_MANAGED_KEYS = [
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_TEMPERATURE",
    "LLM_MAX_TOKENS",
    "LLM_TIMEOUT",
    "LLM_HTTP_PATH",
    "LLM_EMBED_MODEL",
    "EMBED_PROVIDER",
    "EMBED_LOCAL_MODEL",
    "EMBED_LOCAL_REVISION",
    "EMBED_QUERY_INSTRUCTION",
]


class LLMSettingsIn(BaseModel):
    baseUrl: str
    apiKey: str = ""          # 空值表示保留当前已保存的 Key
    model: str
    temperature: Optional[float] = None
    maxTokens: Optional[int] = None
    timeout: Optional[int] = None
    httpPath: Optional[str] = None
    embedModel: Optional[str] = None  # 空值表示保留当前已保存的嵌入模型
    embedProvider: Optional[str] = None  # "api" / "local"
    embedLocalModel: Optional[str] = None  # ModelScope 模型 ID 或本地路径
    embedLocalRevision: Optional[str] = None
    embedQueryInstruction: Optional[str] = None


class LLMTestIn(BaseModel):
    baseUrl: Optional[str] = None
    apiKey: Optional[str] = None   # None 或空值表示使用已保存的 Key
    model: Optional[str] = None
    httpPath: Optional[str] = None


def _upsert_env(updates: dict[str, str]) -> None:
    """原地改写 ``.env``：替换托管键并保留其他内容。

    文件使用不带 BOM 的 UTF-8；python-dotenv 可直接读取。
    """
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8-sig").splitlines()

    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        replaced = False
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                replaced = True
        if not replaced:
            out.append(line)

    if remaining:
        if out and out[-1].strip():
            out.append("")
        out.append("# ---- 由设置界面自动写入 ----")
        for key in _MANAGED_KEYS:
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
        # 保留所有非托管行；这是防御性分支，正常情况下不会剩余。
        for key, value in remaining.items():
            out.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


async def get_llm_settings():
    eff = config.get_effective_llm_settings()
    return {
        "success": True,
        "config": {
            "baseUrl": eff["baseUrl"],
            "apiKeyMasked": mask_key(eff["apiKey"]),
            "apiKeyConfigured": bool((eff["apiKey"] or "").strip()),
            "model": eff["model"],
            "embedModel": eff["embedModel"],
            "embedProvider": eff.get("embedProvider", ""),
            "embedLocalModel": eff.get("embedLocalModel", ""),
            "embedLocalRevision": eff.get("embedLocalRevision", ""),
            "embedQueryInstruction": eff.get("embedQueryInstruction", ""),
            "temperature": eff["temperature"],
            "maxTokens": eff["maxTokens"],
            "timeout": eff["timeout"],
            "httpPath": eff["httpPath"],
            "envPath": str(ENV_PATH),
        },
    }


async def save_llm_settings(req: LLMSettingsIn):
    s = config.settings
    # 读取当前生效值（DB 优先）用于“留空沿用”
    eff = config.get_effective_llm_settings()

    base_url = req.baseUrl.strip().rstrip("/")
    model = req.model.strip()
    if not base_url or not model:
        return {"success": False, "message": "Base URL 和模型名称不能为空"}

    api_key = req.apiKey.strip() or eff["apiKey"] or s.llm_api_key
    temperature = req.temperature if req.temperature is not None else eff["temperature"]
    max_tokens = req.maxTokens if req.maxTokens is not None else eff["maxTokens"]
    timeout = req.timeout if req.timeout is not None else eff["timeout"]
    http_path = (req.httpPath or eff["httpPath"] or s.llm_http_path).strip() or "/chat/completions"
    embed_model = (req.embedModel or "").strip() or eff["embedModel"] or s.llm_embed_model
    embed_provider = (req.embedProvider or "").strip() or eff["embedProvider"] or s.embed_provider
    embed_local_model = (req.embedLocalModel or "").strip() or eff["embedLocalModel"] or s.embed_local_model
    embed_local_revision = ((req.embedLocalRevision or "").strip()
                            or eff.get("embedLocalRevision", "") or s.embed_local_revision)
    embed_query_instruction = ((req.embedQueryInstruction or "").strip()
                               or eff.get("embedQueryInstruction", "")
                               or s.embed_query_instruction)

    # 1) 热生效：写 DB（多 worker 可见，TTL 5s）+ 本 worker 内存/环境变量立即可见
    env_updates = {
        "LLM_BASE_URL": base_url,
        "LLM_API_KEY": api_key,
        "LLM_MODEL": model,
        "LLM_TEMPERATURE": str(temperature),
        "LLM_MAX_TOKENS": str(max_tokens),
        "LLM_TIMEOUT": str(timeout),
        "LLM_HTTP_PATH": http_path,
        "LLM_EMBED_MODEL": embed_model,
        "EMBED_PROVIDER": embed_provider,
        "EMBED_LOCAL_MODEL": embed_local_model,
        "EMBED_LOCAL_REVISION": embed_local_revision,
        "EMBED_QUERY_INSTRUCTION": embed_query_instruction,
    }
    # DB 为准（多 worker 可见）
    try:
        from .. import db as _db
        await _db.database.set_global_configs(env_updates)
    except Exception:
        pass
    # 本 worker 内存立即可见
    s.llm_base_url = base_url
    s.llm_api_key = api_key
    s.llm_model = model
    s.llm_temperature = temperature
    s.llm_max_tokens = max_tokens
    s.llm_timeout = timeout
    s.llm_http_path = http_path
    s.llm_embed_model = embed_model
    s.embed_provider = embed_provider
    s.embed_local_model = embed_local_model
    s.embed_local_revision = embed_local_revision
    s.embed_query_instruction = embed_query_instruction
    os.environ.update(env_updates)
    config.invalidate_llm_cache()

    # 2) 持久化到项目根 .env，冷备（DB 为主，.env 为辅）
    try:
        _upsert_env(env_updates)
    except OSError as exc:
        return {
            "success": False,
            "message": f"配置已保存并多 worker 可见（DB），但写入 .env 失败：{exc}",
        }

    return {
        "success": True,
        "message": "配置已保存并多 worker 热更新（DB TTL 5s 内全量可见，已写入 .env 冷备）",
    }


async def list_embed_local_models():
    """列出已下载的本地嵌入模型 + 当前配置的可用性（只读，不触发下载）。

    系统级接口（无需空间隔离）：扫描 ``data/models/*``（含 config.json 即可用），
    并判定当前 ``EMBED_LOCAL_MODEL`` 是本地命中还是首次使用时才下载。
    """
    from ..rag import local_embed
    eff = config.get_effective_llm_settings()
    configured = (eff.get("embedLocalModel") or "").strip()
    configured_revision = (eff.get("embedLocalRevision") or "").strip()
    try:
        models = local_embed.scan_local_models()
    except Exception:
        models = []
    try:
        status = local_embed.probe_local_model(configured, configured_revision)
    except Exception:
        status = {"configured": False, "resolvable": False, "reason": "检测失败"}
    try:
        loaded = local_embed.get_local_embedder().loaded
        load_error = local_embed.get_local_embedder().last_error
    except Exception:
        loaded = False
        load_error = ""
    return {
        "success": True,
        "configured": configured,
        "provider": eff.get("embedProvider", ""),
        "resolvable": status.get("resolvable", False),
        "reason": status.get("reason", ""),
        "resolvedPath": status.get("path", ""),
        "loaded": loaded,
        "loadError": load_error,
        "models": models,
    }


class EmbedDownloadIn(BaseModel):
    model: str = ""
    revision: str = ""


async def start_embed_download(req: EmbedDownloadIn):
    """提交本地嵌入模型后台下载（幂等；失败手动重试，不自动重试）。

    已下载直返 ready；下载中直返现状；本地目录缺权重直接 failed。
    全局单飞行：已有其它模型在下载（含其它 worker）时回 busy，不排队。
    """
    from ..rag import local_embed
    model = (req.model or "").strip()
    if not model:
        return {"success": False, "message": "模型 ID 不能为空"}
    revision = (req.revision or "").strip()
    if not revision:
        eff = config.get_effective_llm_settings()
        if model == (eff.get("embedLocalModel") or "").strip():
            revision = (eff.get("embedLocalRevision") or "").strip()
    try:
        # 跨进程单飞行（状态文件全局可见；本进程线程级检查在 download_in_background 内）
        active = local_embed.get_active_download()
        if active and (active.get("model") or "") != model:
            return {"success": False, "activeModel": active.get("model"),
                    "message": f"已有下载进行中：{active.get('model')}"}
        st = local_embed.download_in_background(model, revision)
    except Exception as exc:
        return {"success": False, "message": f"提交失败：{exc}"}
    if st.get("state") == "busy":
        return {"success": False, "activeModel": st.get("activeModel"),
                "message": f"已有下载进行中：{st.get('activeModel')}"}
    return {"success": True, **st}


async def embed_download_status(model: str = ""):
    """查询模型下载状态：idle|downloading|ready|failed + 已下 MB + 错误。"""
    from ..rag import local_embed
    try:
        st = local_embed.get_download_status((model or "").strip())
    except Exception as exc:
        return {"success": False, "message": f"查询失败：{exc}"}
    return {"success": True, **st}


async def embed_download_active():
    """查询当前进行中的下载（切 Hub 回来后恢复轮询用；无则回 active: None）。

    顺带做过期判定：downloading 但心跳超 5min 未更新，就地改 failed（可重试）。
    """
    from ..rag import local_embed
    try:
        active = local_embed.get_active_download()
    except Exception as exc:
        return {"success": False, "message": f"查询失败：{exc}"}
    if not active:
        return {"success": True, "active": None}
    return {"success": True, "active": active}


async def list_llm_models(baseUrl: str = "", apiKey: str = ""):
    """从 OpenAI 兼容的 ``/models`` 端点列出可用模型。

    使用已配置或调用方提供的 Base URL 与 Key 请求 ``{baseUrl}/models``，返回模型 ID
    列表；同时支持 OpenAI 兼容结构和 Ollama 原生结构作为回退。
    """
    s = config.settings
    target = (baseUrl or s.llm_base_url or "").strip().rstrip("/")
    key = (apiKey or "").strip() or s.llm_api_key

    if not target:
        return {"success": False, "message": "请先填写 Base URL", "models": []}

    # 用配置里的超时（默认 120s），给外部/较慢的 API 更充裕的时间。
    timeout = s.llm_timeout or 15
    url = f"{target}/models"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {key or ''}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        hint = {
            401: "API Key 无效或未填写",
            403: "无权限，请检查 API Key",
            404: "Models 端点不存在（请确认 Base URL 是否包含 /v1）",
        }.get(exc.code, "")
        msg = f"HTTP {exc.code}"
        if hint:
            msg += f"：{hint}"
        if detail:
            msg += f"（{detail}）"
        return {"success": False, "message": msg, "models": []}
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, socket.timeout) or isinstance(reason, TimeoutError):
            msg = (
                f"连接超时（>{timeout}s）：{target}/models。"
                "后端主机可能无法直连该域名——请确认：① 后端所在机器有外网访问；"
                "② 若处于公司/校园网，可能需要设置 HTTPS_PROXY 环境变量让后端走代理。"
            )
        elif isinstance(reason, socket.gaierror):
            msg = f"域名解析失败：{target}。请检查 Base URL 是否拼写正确或 DNS 是否可用。"
        elif isinstance(reason, ConnectionRefusedError):
            msg = f"连接被拒绝：{target}。请确认服务地址与端口。"
        else:
            msg = f"无法连接到 {target}：{reason}"
        return {"success": False, "message": msg, "models": []}
    except Exception as exc:
        return {
            "success": False,
            "message": f"无法连接到 {target}：{exc}",
            "models": [],
        }

    models: list[str] = []
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            for m in data["data"]:
                mid = m.get("id") if isinstance(m, dict) else None
                if mid:
                    models.append(str(mid))
        elif isinstance(data.get("models"), list):  # Ollama 原生结构回退
            for m in data["models"]:
                name = m.get("name") if isinstance(m, dict) else None
                if name:
                    models.append(str(name))

    # 在保持顺序的前提下去重。
    seen: set[str] = set()
    ordered: list[str] = []
    for m in models:
        if m not in seen:
            seen.add(m)
            ordered.append(m)

    if not ordered:
        # Key 模型无关，/models 空时回落常见模型，避免前端选不到 2.5-flash
        fallback = ["agnes-2.5-flash", "agnes-2.5-pro", "agnes-2.0-flash"]
        return {
            "success": True,
            "message": "模型列表为空，已回落常用模型；Key 全局可用，直接填模型名直调 /v1/chat/completions 即可",
            "models": fallback,
        }
    # 确保 2.5-flash 始终可见（Key 模型无关，/models 可能滞后）
    for must in ["agnes-2.5-flash", "agnes-2.0-flash"]:
        if must not in ordered:
            ordered.append(must)
    return {"success": True, "models": ordered}


async def test_llm_connection(req: LLMTestIn):
    s = config.settings
    base_url = (req.baseUrl or s.llm_base_url or "").strip().rstrip("/")
    api_key = (req.apiKey or "").strip() or s.llm_api_key
    model = (req.model or s.llm_model or "").strip()
    http_path = (req.httpPath or s.llm_http_path or "/chat/completions").strip()

    if not base_url:
        return {"success": False, "message": "请先填写 Base URL"}

    # 用配置里的超时（默认 120s），避免本地大模型首次推理时被硬超时误判为失败。
    timeout = s.llm_timeout or 120

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }).encode("utf-8")

    request = urllib.request.Request(
        f"{base_url}{http_path}",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key or ''}",
        },
        method="POST",
    )

    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        latency_ms = int((time.monotonic() - start) * 1000)
        served_model = body.get("model") or model
        return {
            "success": True,
            "message": f"连接成功（模型: {served_model}，耗时 {latency_ms}ms）",
            "latencyMs": latency_ms,
        }
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        hint = {
            401: "API Key 无效或未填写",
            403: "无权限，请检查 API Key",
            404: "接口路径不存在，请检查 Base URL / HTTP Path",
            429: "触发限流，稍后再试",
        }.get(exc.code, "")
        msg = f"HTTP {exc.code}"
        if hint:
            msg += f"：{hint}"
        if detail:
            msg += f"（{detail}）"
        return {"success": False, "message": msg}
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        # 本地大模型首次推理可能很慢，超时不等于连不通。
        return {
            "success": False,
            "message": f"请求超时（>{timeout}s）：{base_url}。本地大模型首次加载/推理较慢，建议调大 LLM_TIMEOUT 或换用小模型后重试。",
        }
    except Exception as exc:
        return {"success": False, "message": f"无法连接到 {base_url}：{exc}"}


# ---------------------------------------------------------------------------
# 集成服务配置（联网搜索 web_search 技能）
#   * ``GET  /api/settings/integration``  -> 当前 BOCHA key 状态（脱敏）+ provider
#   * ``POST /api/settings/integration``  -> 保存 BOCHA_API_KEY / WEB_SEARCH_PROVIDER
#     写入 .env（重启后仍有效）并即时更新 os.environ（当前 worker 立即生效）。
#     注：uvicorn 多 worker 下其它 worker 需重启后才同步环境变量。
#
#   web_search 默认使用无需 key 的 DuckDuckGo（开箱即用）；BOCHA_API_KEY 为
#   可选增强项（配置后自动获得更高质量结果）。WEB_SEARCH_PROVIDER 取值：
#   'duckduckgo'（默认）| 'bocha' | 'wikipedia'。
# ---------------------------------------------------------------------------
class IntegrationSettingsIn(BaseModel):
    bochaApiKey: str = ""          # 空 -> 沿用已保存的 key（可选增强项，非必填）
    webSearchProvider: str = ""    # 'duckduckgo' | 'bocha' | 'wikipedia'；空 -> 沿用已保存


async def get_integration_settings():
    key = os.environ.get("BOCHA_API_KEY", "")
    return {
        "success": True,
        "config": {
            "bochaApiKeyMasked": mask_key(key),
            "bochaConfigured": bool(key.strip()),
            "webSearchProvider": (os.environ.get("WEB_SEARCH_PROVIDER") or "duckduckgo").strip(),
        },
    }


async def save_integration_settings(req: IntegrationSettingsIn):
    provider = (req.webSearchProvider or "").strip()
    if provider and provider not in ("duckduckgo", "bocha", "wikipedia"):
        return {"success": False, "message": "WEB_SEARCH_PROVIDER 仅支持 duckduckgo / bocha / wikipedia"}

    updates: dict[str, str] = {}
    if req.bochaApiKey and req.bochaApiKey.strip():
        updates["BOCHA_API_KEY"] = req.bochaApiKey.strip()
    if provider:
        updates["WEB_SEARCH_PROVIDER"] = provider

    if not updates:
        return {"success": False, "message": "没有需要保存的改动（key 与 provider 均为空）"}

    # 1) 即时生效：当前 worker 后续调用 web_search 技能时可直接读取到新值。
    os.environ.update(updates)

    # 2) 持久化到项目根 .env，重启后端后仍然有效。
    try:
        _upsert_env(updates)
    except OSError as exc:
        return {
            "success": False,
            "message": f"配置已在本次运行中生效，但写入 .env 失败：{exc}",
        }

    return {
        "success": True,
        "message": "集成配置已保存（已写入 .env）；多 worker 部署下建议重启后端以全量生效",
    }
