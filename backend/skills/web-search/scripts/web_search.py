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

纯标准库实现（urllib + json + re），零第三方依赖，契合项目零重依赖约定。
"""
from __future__ import annotations

import html as _html
import json
import os
import re as _re
import sys
import urllib.parse
import urllib.request

# 博查 AI 搜索端点（POST，Bearer 认证）
BOCHA_URL = "https://api.bochaai.com/v1/web-search"
# DuckDuckGo HTML 端点（POST form，零密钥）
DDG_HTML_URL = "https://html.duckduckgo.com/html/"
# 默认 provider：无需 key 的 DuckDuckGo
DEFAULT_PROVIDER = "duckduckgo"
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


def _search_duckduckgo(query: str, max_results: int) -> list:
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
    with urllib.request.urlopen(req, timeout=12) as resp:
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


def _search_bocha(query: str, max_results: int, freshness: str):
    """博查搜索；未配置 key 返回 None（触发降级）。"""
    key = (os.environ.get("BOCHA_API_KEY") or "").strip()
    if not key:
        return None
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
    with urllib.request.urlopen(req, timeout=12) as resp:
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


def _search_wikipedia(query: str, max_results: int):
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
    with urllib.request.urlopen(req, timeout=8) as resp:
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

    chain = _resolve_chain()
    last_err = ""
    for prov in chain:
        results = None
        try:
            if prov == "duckduckgo":
                results = _search_duckduckgo(query, max_results)
            elif prov == "bocha":
                results = _search_bocha(query, max_results, freshness)
                if results is None:
                    last_err = "未配置 BOCHA_API_KEY"
                    continue
            elif prov == "wikipedia":
                results = _search_wikipedia(query, max_results)
            else:
                continue
        except Exception as exc:
            last_err = f"{prov} 搜索异常: {exc}"
            continue

        if not results:
            last_err = f"{prov} 无可用结果"
            continue

        print(
            json.dumps(
                {"success": True, "provider": prov, "query": query, "results": results},
                ensure_ascii=False,
            )
        )
        return

    print(
        json.dumps(
            {
                "success": False,
                "provider": chain[-1],
                "error": f"所有检索源均失败：{last_err or '未知原因'}",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
