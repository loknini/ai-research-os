#!/usr/bin/env python3
"""web_search — 通用联网搜索技能（工具型，SkillBridge 契约）。

stdin  接收 JSON 参数：{"query": str, "max_results": int, "freshness": str}
stdout 输出 JSON 结果：{"success": bool, "provider": str, "query": str, "results": [...]}

后端选择（环境变量 WEB_SEARCH_PROVIDER）：
* duckduckgo（默认，零密钥、免注册、开箱即用）—— 抓 html.duckduckgo.com，
  无需任何 key，是默认的无依赖联网检索源。
* bocha（博查 AI 搜索，bochaai.com，国内直连，OpenAI 兼容格式）——
  可选增强项，仅当配置了 BOCHA_API_KEY 时才会参与检索；质量更高、
  返回带大模型摘要的结果。免费额度用尽后按量计费。
* wikipedia——零密钥兜底，仅覆盖百科类内容，作为最后防线。

默认检索链（无需任何配置即可工作）：
  duckduckgo →（若配置了 BOCHA_API_KEY 则插入 bocha）→ wikipedia
即：开箱默认走 DuckDuckGo 联网；填了 BOCHA_API_KEY 会自动获得更高
质量结果；都拿不到时退到 Wikipedia 兜底，避免静默失败。

输出契约（成功与失败同形，便于调用方解析）：
  成功：{success, provider, engine, status:"ok", query, results,
         uncertainty[], warnings[], attempts[]}
  失败：{success:false, provider, engine, status:"unavailable", query,
         results:[], uncertainty[], warnings[], error, attempts[]}
其中 attempts 逐条记录 {provider, ok, error?, durationSeconds, keyIndex?}；
uncertainty 是对事实的怀疑，warnings 是对路由的说明（成功也可能非空）。

纯标准库实现（urllib + json + re + socket + time），零第三方依赖，
契合项目零重依赖约定。
"""
from __future__ import annotations

import html as _html
import json
import os
import re as _re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# 博查 AI 搜索端点（POST，Bearer 认证）
BOCHA_URL = "https://api.bochaai.com/v1/web-search"
# DuckDuckGo HTML 端点（POST form，零密钥）
DDG_HTML_URL = "https://html.duckduckgo.com/html/"
# 默认 provider：无需 key 的 DuckDuckGo
DEFAULT_PROVIDER = "duckduckgo"
# 各源单次请求超时（秒）。总量预算 duckduckgo 8 + bocha 8 + wikipedia 5 = 21s，
# 加一次超时重试仍低于技能 timeout（30s），避免被 skills_bridge 到点杀进程。
TIMEOUTS = {"duckduckgo": 8, "bocha": 8, "wikipedia": 5}
# freshness 仅 Bocha 后端支持
VALID_FRESHNESS = ("day", "week", "month", "year")
UA = "AI-Research-OS/1.0 (research workbench)"
# 浏览器级 UA：DuckDuckGo 对默认 python-urllib UA 会限流/拦爬虫
DDG_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _strip_html(s: str) -> str:
    """去掉 HTML 标签并反转义实体。"""
    s = _re.sub(r"<[^>]+>", "", s or "")
    return _html.unescape(s).strip()


def _decode_ddg_url(href: str) -> str:
    """DuckDuckGo 把真实链接包成 //duckduckgo.com/l/?uddg=<urlencoded>，还原之。"""
    if "uddg=" in href:
        m = _re.search(r"uddg=([^&]+)", href)
        if m:
            return urllib.parse.unquote(m.group(1))
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://html.duckduckgo.com" + href
    return href


def _search_duckduckgo(query: str, max_results: int, timeout: int = 8) -> list:
    """DuckDuckGo HTML 端点检索；零密钥、免注册。

    返回标准结果列表；若页面结构变化导致解析不到任何条目，返回空列表
    （由上层决定降级）。
    """
    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    req = urllib.request.Request(
        DDG_HTML_URL,
        data=data,
        headers={
            "User-Agent": DDG_UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        page = resp.read().decode("utf-8", errors="ignore")

    links = _re.findall(
        r'class="result__a"\s+href="([^"]+)"[^>]*>(.*?)</a>', page, _re.S
    )
    snips = _re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', page, _re.S)

    results = []
    for i, (href, title_html) in enumerate(links):
        title = _strip_html(title_html)
        url = _decode_ddg_url(href)
        snippet = _strip_html(snips[i]) if i < len(snips) else ""
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "published": "",
            }
        )
        if len(results) >= max_results:
            break
    return results


def _bocha_keys() -> list:
    """BOCHA_API_KEY 支持逗号分隔多 key；401/403/429 时轮换（不泄 key）。"""
    raw = os.environ.get("BOCHA_API_KEY") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def _short_err(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return str(getattr(exc, "reason", exc))[:120]
    return str(exc)[:120]


def _is_auth_or_quota_error(exc: Exception) -> bool:
    return isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 429)


def _is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    return isinstance(exc, urllib.error.URLError) and isinstance(
        exc.reason, (socket.timeout, TimeoutError)
    )


def _search_bocha(query: str, max_results: int, freshness: str, key: str, timeout: int = 8):
    """单 key 博查搜索；异常直接抛出，由上层记录 attempts 并决定轮换/降级。"""
    payload = {"query": query, "summary": True, "count": max_results}
    if freshness:
        payload["freshness"] = freshness
    req = urllib.request.Request(
        BOCHA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": UA,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    # Bocha 返回 {code, data: {webPages: {value: [...]}}}
    pages = ((data.get("data") or {}).get("webPages") or {}).get("value") or []
    results = []
    for p in pages[:max_results]:
        results.append(
            {
                "title": p.get("name") or "",
                "url": p.get("url") or "",
                "snippet": p.get("summary") or p.get("snippet") or "",
                "published": p.get("dateLastCrawled") or p.get("datePublished") or "",
            }
        )
    return results


def _search_wikipedia(query: str, max_results: int, timeout: int = 5):
    """Wikipedia API 零密钥兜底（zh.wikipedia.org）。"""
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": max_results,
            "format": "json",
            "utf8": 1,
        }
    )
    url = f"https://zh.wikipedia.org/w/api.php?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    hits = (data.get("query") or {}).get("search") or []
    results = []
    for h in hits:
        title = h.get("title") or ""
        snippet = (h.get("snippet") or "").replace('<span class="searchmatch">', "").replace("</span>", "")
        results.append(
            {
                "title": title,
                "url": f"https://zh.wikipedia.org/wiki/{urllib.parse.quote(title)}",
                "snippet": snippet,
                "published": "",
            }
        )
    return results


def _resolve_chain() -> list[str]:
    """返回要依次尝试的 provider 列表（去重保序）。

    规则：
    * 显式设置 WEB_SEARCH_PROVIDER 则以其为首选；
    * 兜底顺序固定为 duckduckgo（无 key 可用）→ bocha（仅在有 key 时）→ wikipedia；
    * 默认（未设置）即 duckduckgo 优先、wikipedia 兜底，开箱即用。
    """
    explicit = (os.environ.get("WEB_SEARCH_PROVIDER") or "").strip().lower()
    has_bocha = bool(os.environ.get("BOCHA_API_KEY", "").strip())

    primary = explicit if explicit in ("bocha", "wikipedia", "duckduckgo") else DEFAULT_PROVIDER

    fallbacks = ["duckduckgo"]
    if has_bocha:
        fallbacks.append("bocha")
    fallbacks.append("wikipedia")

    # primary 永远排在最前（显式意图优先）；其余按兜底顺序补，去重保序。
    chain: list[str] = [primary]
    for p in fallbacks:
        if p not in chain:
            chain.append(p)
    return chain


def _run_simple_provider(prov: str, query: str, max_results: int):
    """跑 duckduckgo / wikipedia 单源（含一次超时重试）。

    返回 (results|[], attempts, warnings)。
    """
    fn = _search_duckduckgo if prov == "duckduckgo" else _search_wikipedia
    timeout = TIMEOUTS[prov]
    attempts, warnings = [], []
    for trial in (1, 2):
        t0 = time.perf_counter()
        try:
            results = fn(query, max_results, timeout)
            attempts.append(
                {"provider": prov, "ok": True, "durationSeconds": round(time.perf_counter() - t0, 2)}
            )
            return results or [], attempts, warnings
        except Exception as exc:
            dt = round(time.perf_counter() - t0, 2)
            attempts.append(
                {"provider": prov, "ok": False, "error": _short_err(exc), "durationSeconds": dt}
            )
            # 仅快速失败（耗时不足一次完整超时，多为瞬时抖动）才重试一次；
            # 慢失败直接降级，保证总量预算 duckduckgo 8 + bocha 8 + wikipedia 5，
            # 远低于技能 timeout（30s），不被 skills_bridge 到点杀进程。
            if trial == 1 and _is_timeout_error(exc) and dt < timeout:
                warnings.append(f"{prov} 请求超时，已重试一次")
                continue
            return [], attempts, warnings
    return [], attempts, warnings


def _run_bocha(query: str, max_results: int, freshness: str):
    """跑 bocha（含多 key 轮换）。

    返回 (results|None, attempts, warnings, key_index|None)。
    None 表示不可用（无 key），调用方跳过；[] 表示可用但失败/无结果。
    """
    keys = _bocha_keys()
    if not keys:
        return None, [], ["bocha 未配置 key，已跳过"], None
    attempts, warnings = [], []
    multi = len(keys) > 1
    for i, key in enumerate(keys):
        t0 = time.perf_counter()
        try:
            results = _search_bocha(query, max_results, freshness, key, TIMEOUTS["bocha"])
            entry: dict = {
                "provider": "bocha",
                "ok": True,
                "durationSeconds": round(time.perf_counter() - t0, 2),
            }
            if multi:
                entry["keyIndex"] = i
            attempts.append(entry)
            return results or [], attempts, warnings, (i if multi else None)
        except Exception as exc:
            entry = {
                "provider": "bocha",
                "ok": False,
                "error": _short_err(exc),
                "durationSeconds": round(time.perf_counter() - t0, 2),
            }
            if multi:
                entry["keyIndex"] = i
            attempts.append(entry)
            if _is_auth_or_quota_error(exc) and i < len(keys) - 1:
                warnings.append(f"bocha 第{i + 1}个key失效（{_short_err(exc)}），已轮换")
                continue
            return [], attempts, warnings, None
    return [], attempts, warnings, None


def main() -> None:
    try:
        params = json.loads(sys.stdin.read() or "{}")
    except Exception:
        params = {}
    query = (params.get("query") or "").strip()
    try:
        max_results = min(int(params.get("max_results") or 5), 10)
    except (TypeError, ValueError):
        max_results = 5
    freshness = (params.get("freshness") or "").strip()

    if not query:
        print(json.dumps({"success": False, "error": "缺少 query 参数"}, ensure_ascii=False))
        return

    warnings: list = []
    if freshness and freshness not in VALID_FRESHNESS:
        warnings.append(f"freshness '{freshness}' 不支持，已忽略（仅支持 day/week/month/year）")
        freshness = ""
    if freshness and not _bocha_keys():
        warnings.append("freshness 仅 bocha 支持，当前未配置 key，已忽略")
        freshness = ""

    chain = _resolve_chain()
    attempts_all: list = []
    last_err = ""
    for prov in chain:
        if prov == "bocha":
            results, atts, warns, _ = _run_bocha(query, max_results, freshness)
            attempts_all.extend(atts)
            warnings.extend(warns)
            if results is None:
                continue
        elif prov in ("duckduckgo", "wikipedia"):
            results, atts, warns = _run_simple_provider(prov, query, max_results)
            attempts_all.extend(atts)
            warnings.extend(warns)
        else:
            continue

        if not results:
            last_err = f"{prov} 无可用结果"
            continue

        print(
            json.dumps(
                {
                    "success": True,
                    "provider": prov,
                    "engine": prov,
                    "status": "ok",
                    "query": query,
                    "results": results,
                    "uncertainty": [],
                    "warnings": warnings,
                    "attempts": attempts_all,
                },
                ensure_ascii=False,
            )
        )
        return

    print(
        json.dumps(
            {
                "success": False,
                "provider": chain[-1],
                "engine": chain[-1],
                "status": "unavailable",
                "query": query,
                "results": [],
                "uncertainty": [],
                "warnings": warnings,
                "error": f"所有检索源均失败：{last_err or '未知原因'}",
                "attempts": attempts_all,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
