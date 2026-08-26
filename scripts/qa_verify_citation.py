#!/usr/bin/env python3
"""
QA 验证脚本：citation 模块
=========================

覆盖范围：
  1. Crossref 搜索 query.title= 字段限定（避免 BM25 把问句式长标题召回错乱）
  2. arXiv fetch by id（Crossref 不收录的预印本 fallback）
  3. resolve 三段式（DOI → arXiv → 标题关键词兜底）
  4. /api/citation/resolve HTTP 端点
  5. generate_bibtex 对 preprint (@misc) 与 article 的区分
  6. Crossref 关键字搜索关键词抽取（停用词过滤）

所有外部 API 调用都通过 monkeypatch 注入（urllib.request.urlopen），
脚本不触网、不写库，可重复运行。
"""

import json
import sys
from unittest.mock import patch, MagicMock
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))  # 把项目根加入 sys.path（backend/server 是它的子包）
sys.path.insert(0, str(ROOT / "scripts"))

import citation_service  # noqa: E402


# ---------- 构造假响应 ----------

def _crossref_ok(titles):
    """构造一个 Crossref success / has-items 响应。"""
    items = []
    for t in titles:
        items.append({
            "DOI": f"10.1234/{t.lower().replace(' ', '-')[:20]}",
            "title": [t],
            "author": [{"given": "John", "family": "Doe"}],
            "published-print": {"date-parts": [[2024]]},
            "container-title": ["CVPR"],
            "short-container-title": ["CVPR"],
            "volume": "1",
            "issue": "1",
            "page": "1-10",
            "publisher": "IEEE",
            "type": "journal-article",
            "URL": "https://example.com",
        })
    msg = {"status": "ok", "message": {"items": items, "total-results": len(items)}}
    return _json_bytes(msg)


def _crossref_not_found():
    msg = {"status": "ok", "message": {"items": [], "total-results": 0}}
    return _json_bytes(msg)


def _arxiv_ok(title="A Vision Language Paper", arxiv_id="2608.99999"):
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/{arxiv_id}v1</id>
    <title>{title}</title>
    <author><name>Alice Researcher</name></author>
    <author><name>Bob Engineer</name></author>
    <published>2026-08-01T00:00:00Z</published>
  </entry>
</feed>"""
    return body.encode("utf-8")


def _arxiv_empty():
    body = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"/>
"""
    return body.encode("utf-8")


def _json_bytes(obj):
    return json.dumps(obj).encode("utf-8")


# ---------- 单测 ----------

def test_search_title_field_in_url():
    """search_papers 必须把 query.title= 也加进 URL（不只是 query=）。"""
    captured = {}

    def fake_urlopen(req, timeout=30):
        captured["url"] = req.full_url
        m = MagicMock()
        m.__enter__ = lambda s: s
        m.__exit__ = lambda s, a, b, c: None
        m.read = lambda: _crossref_ok(["any paper"])
        return m

    with patch.object(citation_service.urllib.request, "urlopen", side_effect=fake_urlopen):
        r = citation_service.search_papers("What's the Catch?", rows=5)
    assert r["success"], "search returned failure"
    assert "query.title=" in captured["url"], f"query.title= missing: {captured['url']}"
    assert "query=What" in captured["url"], "query= missing"
    print("  [1] search_papers URL includes both query= and query.title= ✓")


def test_search_title_field_recall():
    """query= 全文搜索 vs query.title= 字段搜索：title= 应该至少能命中至少 1 个相关结果。"""
    # 模拟「实测试」：query= 关键词被 BM25 误吃掉；query.title= 命中真相关论文
    long_title = "What's the Catch? Evaluating Temporal Consistency in Vision-Language Models"

    def fake_urlopen(req, timeout=30):
        url = req.full_url
        if "query.title=" in url:
            payload = _crossref_ok([
                "Evaluating Temporal Consistency in Vision-Language Models",
                "Other paper A",
            ])
        else:  # 纯 query= 全文
            payload = _crossref_ok([
                "DRISHTIKON-P: A Multilingual Dataset",  # 不相关
                "Evaluating large language models for endodontic",  # 不相关
            ])
        m = MagicMock()
        m.__enter__ = lambda s: s
        m.__exit__ = lambda s, a, b, c: None
        m.read = lambda: payload
        return m

    with patch.object(citation_service.urllib.request, "urlopen", side_effect=fake_urlopen):
        r = citation_service.search_papers(long_title, rows=5)
    titles = [p["title"] for p in r["papers"]]
    assert any("Temporal Consistency" in t for t in titles), (
        f"query.title= 没有召回相关论文: {titles}"
    )
    print("  [2] search with query.title= 召回相关论文 ✓")


def test_fetch_arxiv_paper():
    """arXiv 单条查询：解析 entry → Paper（结构化 authors + arxiv_id）"""
    def fake_urlopen(req, timeout=30):
        assert "id_list=2608.99999" in req.full_url
        m = MagicMock()
        m.__enter__ = lambda s: s
        m.__exit__ = lambda s, a, b, c: None
        m.read = lambda: _arxiv_ok(arxiv_id="2608.99999")
        return m

    with patch.object(citation_service.urllib.request, "urlopen", side_effect=fake_urlopen):
        r = citation_service.fetch_arxiv_paper("2608.99999")
    assert r["success"] is True
    p = r["paper"]
    assert p["arxiv_id"] == "2608.99999v1"
    assert p["title"].startswith("A Vision Language Paper")
    # 作者结构化：given/family
    assert p["authors"][0]["family"] == "Researcher"
    assert p["authors"][0]["given"] == "Alice"
    assert p["authors"][1]["family"] == "Engineer"
    assert p["year"] == 2026
    assert r["source"] == "arxiv"
    print("  [3] fetch_arxiv_paper 解析 entry → 结构化 Paper + arxiv_id ✓")


def test_resolve_doi_first():
    """resolve_paper 优先 DOI (Crossref)。"""
    call_count = {"n": 0}

    def fake_urlopen(req, timeout=30):
        call_count["n"] += 1
        url = req.full_url
        m = MagicMock()
        m.__enter__ = lambda s: s
        m.__exit__ = lambda s, a, b, c: None
        # /works/<doi>/transform/application/json 是 DOI 直查（返回单个 item）
        # /works?... 是搜索（返回 message.items 列表）
        if "/works/10.1234" in url or "transform/application/json" in url:
            item = {
                "DOI": "10.1234/test",
                "title": ["Resolved By DOI"],
                "author": [{"given": "John", "family": "Doe"}],
                "published-print": {"date-parts": [[2024]]},
                "container-title": ["CVPR"],
                "short-container-title": ["CVPR"],
                "volume": "1",
                "issue": "1",
                "page": "1-10",
                "publisher": "IEEE",
                "type": "journal-article",
                "URL": "https://example.com",
            }
            m.read = lambda: json.dumps(item).encode("utf-8")
        else:
            m.read = lambda: _crossref_ok(["Resolved By DOI"])
        return m

    with patch.object(citation_service.urllib.request, "urlopen", side_effect=fake_urlopen):
        r = citation_service.resolve_paper(doi="10.1234/test", title="anything", arxiv_id="1234.5678")
    if not r.get("success"):
        raise AssertionError(f"resolve failed: {r}")
    if r.get("source") != "crossref-doi":
        raise AssertionError(f"source 应该 crossref-doi，实际 {r.get('source')}")
    title = r["paper"].get("title", "")
    if not title.startswith("Resolved"):
        raise AssertionError(f"paper.title 错: {title!r}")
    if call_count["n"] != 1:
        raise AssertionError(f"应该仅 1 次调用，实际 {call_count['n']}")
    print("  [4] resolve_paper: DOI 成功（仅 1 次调用）✓")


def test_resolve_arxiv_fallback():
    """resolve_paper: DOI 失败 → arXiv。"""
    calls = {"arxiv": False, "crossref": False}

    def fake_urlopen(req, timeout=30):
        url = req.full_url
        if "crossref.org" in url:
            calls["crossref"] = True
            # 模拟 DOI 404
            err = citation_service.urllib.error.HTTPError(
                url, 404, "Not Found", {}, None
            )
            raise err
        if "arxiv.org" in url:
            calls["arxiv"] = True
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, a, b, c: None
            m.read = lambda: _arxiv_ok(arxiv_id="2608.12345")
            return m
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(citation_service.urllib.request, "urlopen", side_effect=fake_urlopen):
        r = citation_service.resolve_paper(doi="10.bad", arxiv_id="2608.12345", title="ignored")
    assert calls["arxiv"] and calls["crossref"]
    assert r["source"] == "arxiv"
    assert r["paper"]["arxiv_id"].startswith("2608.12345")
    print("  [5] resolve_paper: DOI 失败 → arXiv fallback ✓")


def test_resolve_title_fallback():
    """resolve_paper: DOI + arXiv 都缺 → 标题关键词兜底。"""
    def fake_urlopen(req, timeout=30):
        url = req.full_url
        m = MagicMock()
        m.__enter__ = lambda s: s
        m.__exit__ = lambda s, a, b, c: None
        if "query.title=" in url:
            m.read = lambda: _crossref_ok(["Temporal Consistency Vision-Language Models"])
        elif "arxiv.org" in url:
            m.read = lambda: _arxiv_empty()
        else:
            raise AssertionError(f"unexpected: {url}")
        return m

    with patch.object(citation_service.urllib.request, "urlopen", side_effect=fake_urlopen):
        r = citation_service.resolve_paper(
            title="What's the Catch? Evaluating Temporal Consistency in Vision-Language Models"
        )
    assert r["source"] == "crossref-title"
    assert "Temporal Consistency" in r["paper"]["title"]
    print("  [6] resolve_paper: 标题关键词兜底 ✓")


def test_resolve_all_fail():
    """三段全部 0 命中 → success=False + 提示信息。"""
    def fake_urlopen(req, timeout=30):
        url = req.full_url
        m = MagicMock()
        m.__enter__ = lambda s: s
        m.__exit__ = lambda s, a, b, c: None
        if "arxiv.org" in url:
            m.read = lambda: _arxiv_empty()
        else:
            m.read = lambda: _crossref_not_found()
        return m

    with patch.object(citation_service.urllib.request, "urlopen", side_effect=fake_urlopen):
        r = citation_service.resolve_paper(title="Nonexistent Title XYZ123")
    assert r["success"] is False
    assert "未找到" in r["message"]
    print("  [7] resolve_paper: 三段全失败 → 友好失败 ✓")


def test_extract_keywords():
    """_extract_keywords 应过滤停用词 + 限定 token 数 + 剔除短词。"""
    kw = citation_service._extract_keywords(
        "What's the Catch? Evaluating Temporal Consistency in Vision-Language Models"
    )
    tokens = kw.lower().split()
    if "what" in tokens:
        raise AssertionError(f"'what' 应该在停用词表内: {kw}")
    if "the" in tokens:
        raise AssertionError(f"'the' 应该在停用词表内: {kw}")
    if "catch" not in tokens:
        raise AssertionError(f"'catch' 应保留: {kw}")
    if "Temporal" not in kw:
        raise AssertionError(f"Temporal 应保留: {kw}")
    if "Vision-Language" not in kw:
        raise AssertionError(f"Vision-Language 应保留: {kw}")
    if "Models" not in kw:
        raise AssertionError(f"Models 应保留: {kw}")
    if len(tokens) > 6:
        raise AssertionError(f"超过 6 token: {kw}")
    print(f"  [8] _extract_keywords: '{kw}' ✓")


def test_generate_bibtex_preprint():
    """preprint（arxiv_id 或 journal=arXiv）→ @misc，而不是 @article。"""
    paper = {
        "doi": "",
        "title": "An Awesome arXiv Paper",
        "authors": [{"given": "Alice", "family": "Researcher"}],
        "year": 2026,
        "journal": "arXiv",
        "journal_short": "arXiv",
        "arxiv_id": "2608.12345",
        "url": "https://arxiv.org/abs/2608.12345",
    }
    bib = citation_service.generate_bibtex(paper)
    assert bib.startswith("@misc{researcher2026"), f"应使用 @misc: {bib[:60]}"
    assert "howpublished = {arXiv:2608.12345}" in bib
    assert "eprint = {2608.12345}" in bib
    assert "author = {Researcher, Alice}" in bib
    print("  [9] generate_bibtex(@misc for preprint) ✓")


def test_generate_bibtex_journal_article():
    """期刊论文 → @article + journal/volume/pages 字段。"""
    paper = {
        "doi": "10.1109/cvpr.2024.001",
        "title": "A Vision Paper",
        "authors": [{"given": "John", "family": "Doe"}],
        "year": 2024,
        "journal": "CVPR",
        "journal_short": "CVPR",
        "volume": "1",
        "issue": "1",
        "page": "100-110",
        "publisher": "IEEE",
        "type": "journal-article",
        "url": "",
    }
    bib = citation_service.generate_bibtex(paper)
    assert bib.startswith("@article{doe2024"), f"应使用 @article: {bib[:80]}"
    assert "journal = {CVPR}" in bib
    assert "volume = {1}" in bib
    assert "pages = {100-110}" in bib
    assert "howpublished" not in bib
    print("  [10] generate_bibtex(@article for journal) ✓")


def test_http_resolve_endpoint():
    """POST /api/citation/resolve 三参数都能接受（FastAPI schema）。"""
    from backend.server.routers.citation import CitationResolve
    p = CitationResolve(title="foo", doi=None, arxiv_id="2608.12345")
    assert p.title == "foo" and p.doi is None and p.arxiv_id == "2608.12345"
    print("  [11] /api/citation/resolve schema 接受三参数 ✓")


def main():
    print("=" * 60)
    print("citation module QA")
    print("=" * 60)
    tests = [
        test_search_title_field_in_url,
        test_search_title_field_recall,
        test_fetch_arxiv_paper,
        test_resolve_doi_first,
        test_resolve_arxiv_fallback,
        test_resolve_title_fallback,
        test_resolve_all_fail,
        test_extract_keywords,
        test_generate_bibtex_preprint,
        test_generate_bibtex_journal_article,
        test_http_resolve_endpoint,
    ]
    ok = 0
    for t in tests:
        try:
            t()
            ok += 1
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:
            print(f"  ⚠️  {t.__name__}: {type(e).__name__}: {e}")

    print("=" * 60)
    print(f"PASS: {ok}/{len(tests)}")
    if ok != len(tests):
        sys.exit(1)


if __name__ == "__main__":
    main()
