#!/usr/bin/env python3
"""arxiv_reader 工具型技能：从 arXiv 抓取论文并返回结构化 JSON。

纯标准库实现（urllib + xml.etree），无第三方依赖，契合本项目的零依赖约定。
由 SkillBridge 通过 subprocess 调用：stdin 读 JSON 参数，stdout 写 JSON 结果。
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
API_URL = "http://export.arxiv.org/api/query"


def _norm(text: str) -> str:
    """折叠空白，便于 LLM 阅读。"""
    return " ".join((text or "").split())


def parse_atom(xml_text: str) -> list:
    """解析 arXiv Atom 响应为论文 dict 列表（纯标准库，字段缺失时安全跳过）。"""
    root = ET.fromstring(xml_text)
    papers: list = []
    for entry in root.iter(f"{ATOM_NS}entry"):
        raw_id = entry.findtext(f"{ATOM_NS}id") or ""
        arxiv_id = raw_id.rsplit("/", 1)[-1]
        bare = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id

        title = _norm(entry.findtext(f"{ATOM_NS}title"))
        summary = _norm(entry.findtext(f"{ATOM_NS}summary"))
        authors = [a.findtext(f"{ATOM_NS}name") for a in entry.findall(f"{ATOM_NS}author")]
        authors = [a for a in authors if a]
        published = entry.findtext(f"{ATOM_NS}published") or ""

        pdf_url = ""
        abs_url = raw_id
        for link in entry.findall(f"{ATOM_NS}link"):
            href = link.get("href", "")
            if link.get("title") == "pdf" or href.endswith(".pdf"):
                pdf_url = href
            if "abs" in href:
                abs_url = href

        primary = entry.find(f"{ARXIV_NS}primary_category")
        primary_cat = primary.get("term") if primary is not None else ""
        categories = [c.get("term") for c in entry.findall(f"{ATOM_NS}category")]
        comment = entry.findtext(f"{ARXIV_NS}comment") or ""
        doi = entry.findtext(f"{ARXIV_NS}doi") or ""

        papers.append(
            {
                "arxiv_id": bare,
                "versioned_id": arxiv_id,
                "title": title,
                "authors": authors,
                "summary": summary,
                "published": published,
                "pdf_url": pdf_url,
                "url": abs_url,
                "primary_category": primary_cat,
                "categories": categories,
                "comment": comment,
                "doi": doi,
            }
        )
    return papers


def fetch(params: dict) -> dict:
    """根据参数抓取 arXiv，返回结构化结果。"""
    arxiv_id = (params.get("arxiv_id") or "").strip()
    query = (params.get("query") or "").strip()
    try:
        max_results = int(params.get("max_results", 3))
    except (TypeError, ValueError):
        max_results = 3
    max_results = max(1, min(max_results, 20))

    if arxiv_id:
        aid = arxiv_id
        if "arxiv.org/abs/" in aid:
            aid = aid.split("arxiv.org/abs/")[-1]
        elif "arxiv.org/pdf/" in aid:
            aid = aid.split("arxiv.org/pdf/")[-1]
        aid = aid.replace(".pdf", "").strip("/")
        # 注意：arXiv API 的 id_list 是**独立参数**，不能塞进 search_query
        # （否则会被当成 all:id_list:xxx 全文搜索而返回 0 结果）。
        q = urllib.parse.urlencode({"id_list": aid, "max_results": max_results})
        search_label = f"id_list:{aid}"
    elif query:
        q = urllib.parse.urlencode(
            {"search_query": f"all:{query}", "start": 0, "max_results": max_results}
        )
        search_label = f"all:{query}"
    else:
        return {"success": False, "error": "必须提供 arxiv_id 或 query 之一"}
    url = f"{API_URL}?{q}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-research-os/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as exc:
        return {"success": False, "error": f"arXiv 请求失败: {exc}"}

    try:
        papers = parse_atom(data)
    except ET.ParseError as exc:
        return {"success": False, "error": f"arXiv 响应解析失败: {exc}"}

    return {"success": True, "query": search_label, "count": len(papers), "papers": papers}


def main() -> None:
    raw = sys.stdin.read()
    try:
        params = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        params = {}
    if not isinstance(params, dict):
        params = {}
    result = fetch(params)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
