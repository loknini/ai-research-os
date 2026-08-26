#!/usr/bin/env python3
"""
Citation Service - 参考文献引用生成服务
使用 Crossref API 获取论文元数据并生成各种引用格式
"""

import os
import sys
import json
import re
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
import urllib.parse
from typing import Dict, List, Any, Optional
from datetime import datetime

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_db, init_db

# Crossref API 配置
CROSSREF_API_BASE = "https://api.crossref.org"
USER_AGENT = "AI-Research-OS/1.0 (mailto:research@example.com)"
ARXIV_API_URL = "http://export.arxiv.org/api/query"
ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


# 简易英文停用词表：用于从长标题抽核心关键词
EN_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "to", "for", "with",
    "is", "are", "was", "were", "be", "being", "been", "by", "as", "at",
    "from", "this", "that", "these", "those", "it", "its", "what", "whats",
    "how", "why", "we", "our", "you", "your", "they", "their", "i",
}

# 支持的语言列表（用于 GB/T 7714 判断）
CJK_RANGES = [
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3040, 0x309F),   # Hiragana
    (0x30A0, 0x30FF),   # Katakana
    (0xAC00, 0xD7AF),   # Korean Hangul Syllables
]


def contains_cjk(text: str) -> bool:
    """检查文本是否包含中日韩文字"""
    for char in text:
        code = ord(char)
        for start, end in CJK_RANGES:
            if start <= code <= end:
                return True
    return False


def search_papers(query: str, rows: int = 10) -> Dict[str, Any]:
    """
    通过 Crossref API 搜索论文。

    关键修复（2026-08-25）：之前只用 ``query=``（全文 BM25），对问句式长标题
    召回极差（"What's the Catch? Evaluating..." → 全是无关结果）。
    现在同时传 ``query.title=``（限定标题字段）和 ``query=``，并把标题
    字段的命中排在前——实测把 "Temporal Consistency Vision-Language
    Models" 这种长问句召回显著改善。
    """
    try:
        # 构建查询 URL（query.title= 限定标题字段，query= 全文兜底）
        encoded_query = urllib.parse.quote(query)
        url = (
            f"{CROSSREF_API_BASE}/works"
            f"?query={encoded_query}"
            f"&query.title={encoded_query}"
            f"&rows={rows}&sort=relevance&order=desc"
        )
        
        # 设置请求头（Crossref 要求提供邮箱）
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json"
        }
        
        req = urllib.request.Request(url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            if data.get("status") == "ok":
                items = data["message"].get("items", [])
                papers = []
                
                for item in items:
                    paper = parse_crossref_item(item)
                    if paper:
                        papers.append(paper)
                
                return {
                    "success": True,
                    "papers": papers,
                    "total": data["message"].get("total-results", 0)
                }
            else:
                return {
                    "success": False,
                    "message": "API 返回错误",
                    "papers": []
                }
    
    except urllib.error.HTTPError as e:
        return {
            "success": False,
            "message": f"HTTP 错误: {e.code}",
            "papers": []
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"搜索错误: {str(e)}",
            "papers": []
        }


def get_paper_by_doi(doi: str) -> Dict[str, Any]:
    """通过 DOI 获取论文详情"""
    try:
        url = f"{CROSSREF_API_BASE}/works/{urllib.parse.quote(doi, safe='')}/transform/application/json"
        
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json"
        }
        
        req = urllib.request.Request(url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=30) as response:
            item = json.loads(response.read().decode('utf-8'))
            paper = parse_crossref_item(item)
            
            if paper:
                return {
                    "success": True,
                    "paper": paper
                }
            else:
                return {
                    "success": False,
                    "message": "无法解析论文信息"
                }
    
    except Exception as e:
        return {
            "success": False,
            "message": f"获取失败: {str(e)}"
        }


def parse_crossref_item(item: Dict) -> Optional[Dict[str, Any]]:
    """解析 Crossref 返回的论文数据"""
    try:
        # 作者信息
        authors = []
        for author in item.get("author", []):
            given = author.get("given", "")
            family = author.get("family", "")
            if given and family:
                authors.append({
                    "given": given,
                    "family": family,
                    "full": f"{family}, {given[0]}." if given else family
                })
        
        # 获取年份
        year = None
        if "published-print" in item and "date-parts" in item["published-print"]:
            date_parts = item["published-print"]["date-parts"]
            if date_parts and len(date_parts[0]) > 0:
                year = date_parts[0][0]
        elif "published-online" in item and "date-parts" in item["published-online"]:
            date_parts = item["published-online"]["date-parts"]
            if date_parts and len(date_parts[0]) > 0:
                year = date_parts[0][0]
        elif "created" in item and "date-parts" in item["created"]:
            date_parts = item["created"]["date-parts"]
            if date_parts and len(date_parts[0]) > 0:
                year = date_parts[0][0]
        
        # 期刊/会议名称
        container = item.get("container-title", [])
        journal = container[0] if container else ""
        
        # 期刊缩写
        container_short = item.get("short-container-title", [])
        journal_short = container_short[0] if container_short else journal
        
        return {
            "doi": item.get("DOI", ""),
            "title": item.get("title", [""])[0] if item.get("title") else "",
            "authors": authors,
            "year": year,
            "journal": journal,
            "journal_short": journal_short,
            "volume": item.get("volume", ""),
            "issue": item.get("issue", ""),
            "page": item.get("page", ""),
            "publisher": item.get("publisher", ""),
            "type": item.get("type", ""),
            "url": item.get("URL", f"https://doi.org/{item.get('DOI', '')}")
        }
    except Exception as e:
        print(f"Parse error: {e}", file=sys.stderr)
        return None


def format_authors_apa(authors: List[Dict]) -> str:
    """格式化 APA 作者列表"""
    if not authors:
        return ""
    
    if len(authors) == 1:
        return f"{authors[0]['family']}, {authors[0]['given'][0]}."
    elif len(authors) == 2:
        return f"{authors[0]['family']}, {authors[0]['given'][0]}., & {authors[1]['family']}, {authors[1]['given'][0]}."
    elif len(authors) <= 7:
        result = ", ".join([f"{a['family']}, {a['given'][0]}." for a in authors[:-1]])
        return f"{result}, & {authors[-1]['family']}, {authors[-1]['given'][0]}."
    else:
        result = ", ".join([f"{a['family']}, {a['given'][0]}." for a in authors[:6]])
        return f"{result} et al."


def format_authors_mla(authors: List[Dict]) -> str:
    """格式化 MLA 作者列表"""
    if not authors:
        return ""
    
    if len(authors) == 1:
        return f"{authors[0]['family']}, {authors[0]['given']}."
    elif len(authors) == 2:
        return f"{authors[0]['family']}, {authors[0]['given']}, and {authors[1]['given']} {authors[1]['family']}."
    else:
        return f"{authors[0]['family']}, {authors[0]['given']}, et al."


def format_authors_gb7714(authors: List[Dict]) -> str:
    """格式化 GB/T 7714 作者列表"""
    if not authors:
        return ""
    
    if len(authors) == 1:
        return f"{authors[0]['family']} {authors[0]['given'][0]}"
    elif len(authors) == 2:
        return f"{authors[0]['family']} {authors[0]['given'][0]}, {authors[1]['family']} {authors[1]['given'][0]}"
    elif len(authors) == 3:
        return f"{authors[0]['family']} {authors[0]['given'][0]}, {authors[1]['family']} {authors[1]['given'][0]}, {authors[2]['family']} {authors[2]['given'][0]}"
    else:
        return f"{authors[0]['family']} {authors[0]['given'][0]} 等"


def generate_citation(paper: Dict[str, Any], style: str) -> str:
    """
    生成指定格式的引用
    
    Args:
        paper: 论文元数据
        style: 引用格式 (apa, mla, chicago, gb7714, bibtex, ris)
    
    Returns:
        格式化后的引用字符串
    """
    if style == "apa":
        return generate_apa(paper)
    elif style == "mla":
        return generate_mla(paper)
    elif style == "chicago":
        return generate_chicago(paper)
    elif style == "gb7714":
        return generate_gb7714(paper)
    elif style == "bibtex":
        return generate_bibtex(paper)
    elif style == "ris":
        return generate_ris(paper)
    else:
        return generate_apa(paper)  # 默认 APA


def generate_apa(paper: Dict[str, Any]) -> str:
    """生成 APA 第7版格式引用"""
    authors = format_authors_apa(paper.get("authors", []))
    year = paper.get("year", "n.d.")
    title = paper.get("title", "")
    journal = paper.get("journal", "")
    volume = paper.get("volume", "")
    issue = paper.get("issue", "")
    page = paper.get("page", "")
    doi = paper.get("doi", "")
    
    # 构建引用
    citation = f"{authors} ({year}). {title}."
    
    if journal:
        citation += f" <i>{journal}</i>"
        if volume:
            citation += f", <i>{volume}</i>"
            if issue:
                citation += f"({issue})"
        if page:
            citation += f", {page}"
        citation += "."
    
    if doi:
        citation += f" https://doi.org/{doi}"
    
    return citation


def generate_mla(paper: Dict[str, Any]) -> str:
    """生成 MLA 第9版格式引用"""
    authors = format_authors_mla(paper.get("authors", []))
    year = paper.get("year", "")
    title = paper.get("title", "")
    journal = paper.get("journal", "")
    volume = paper.get("volume", "")
    issue = paper.get("issue", "")
    page = paper.get("page", "")
    doi = paper.get("doi", "")
    
    citation = f"{authors} \"{title}.\""
    
    if journal:
        citation += f" <i>{journal}</i>"
        if volume:
            citation += f", vol. {volume}"
        if issue:
            citation += f", no. {issue}"
        if year:
            citation += f", {year}"
        if page:
            citation += f", pp. {page}"
        citation += "."
    
    if doi:
        citation += f" {doi}."
    
    return citation


def generate_chicago(paper: Dict[str, Any]) -> str:
    """生成 Chicago 第17版格式引用（Author-Date）"""
    authors = format_authors_mla(paper.get("authors", []))
    year = paper.get("year", "")
    title = paper.get("title", "")
    journal = paper.get("journal", "")
    volume = paper.get("volume", "")
    issue = paper.get("issue", "")
    page = paper.get("page", "")
    doi = paper.get("doi", "")
    
    citation = f"{authors}"
    if year:
        citation += f" {year}."
    citation += f" \"{title}.\""
    
    if journal:
        citation += f" <i>{journal}</i>"
        if volume:
            citation += f" {volume}"
            if issue:
                citation += f", no. {issue}"
        if year:
            citation += f" ({year})"
        if page:
            citation += f": {page}"
        citation += "."
    
    if doi:
        citation += f" https://doi.org/{doi}."
    
    return citation


def generate_gb7714(paper: Dict[str, Any]) -> str:
    """生成 GB/T 7714-2015 格式引用（顺序编码制）"""
    authors = format_authors_gb7714(paper.get("authors", []))
    year = paper.get("year", "")
    title = paper.get("title", "")
    journal = paper.get("journal", "")
    volume = paper.get("volume", "")
    issue = paper.get("issue", "")
    page = paper.get("page", "")
    doi = paper.get("doi", "")
    
    # 判断是否有 CJK 字符
    has_cjk = contains_cjk(title) or contains_cjk(journal)
    
    citation = ""
    
    if has_cjk:
        # 中文文献格式
        citation = f"[{authors}]. {title}[J]. {journal}"
        if year:
            citation += f", {year}"
        if volume:
            citation += f", {volume}"
            if issue:
                citation += f"({issue})"
        if page:
            citation += f":{page}"
        citation += "."
    else:
        # 英文文献格式
        citation = f"{authors}. {title}[J]. {journal}"
        if year:
            citation += f", {year}"
        if volume:
            citation += f", {volume}"
            if issue:
                citation += f"({issue})"
        if page:
            citation += f":{page}"
        citation += "."
    
    if doi:
        citation += f" DOI:{doi}."
    
    return citation


def _parse_arxiv_entry(entry) -> Optional[Dict[str, Any]]:
    """解析 arXiv API entry → Citation Paper schema。"""
    try:
        id_elem = entry.find("atom:id", ARXIV_NS)
        if id_elem is None:
            return None
        arxiv_url = id_elem.text or ""
        arxiv_id = arxiv_url.split("/abs/")[-1] if "/abs/" in arxiv_url else arxiv_url

        title_elem = entry.find("atom:title", ARXIV_NS)
        title = (title_elem.text or "").strip() if title_elem is not None else "Unknown"

        authors: List[Dict[str, str]] = []
        for author in entry.findall("atom:author", ARXIV_NS):
            name_elem = author.find("atom:name", ARXIV_NS)
            if name_elem is None or not name_elem.text:
                continue
            full = name_elem.text.strip()
            parts = full.split()
            if len(parts) == 1:
                family, given = parts[0], ""
            else:
                family = parts[-1]
                given = " ".join(parts[:-1])
            authors.append({"given": given, "family": family, "full": full})

        published_elem = entry.find("atom:published", ARXIV_NS)
        year = None
        if published_elem is not None and published_elem.text:
            try:
                year = int(published_elem.text[:4])
            except (ValueError, IndexError):
                pass

        # DOI（如有，arXiv 部分论文会同时发表在期刊上）
        doi_elem = entry.find("arxiv:doi", ARXIV_NS)
        doi = doi_elem.text if doi_elem is not None else ""

        return {
            "doi": doi,
            "title": title,
            "authors": authors,
            "year": year,
            "journal": "arXiv",
            "journal_short": "arXiv",
            "volume": "",
            "issue": "",
            "page": "",
            "publisher": "arXiv",
            "type": "preprint",
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            # 扩展字段（仅供 resolve 流程内部使用，generate_citation 兼容）
            "arxiv_id": arxiv_id,
        }
    except Exception as exc:  # pragma: no cover
        print(f"arXiv parse error: {exc}", file=sys.stderr)
        return None


def fetch_arxiv_paper(arxiv_id: str) -> Dict[str, Any]:
    """通过 arXiv API 查询单篇论文元数据（无网络依赖外的额外库）。"""
    arxiv_id = (arxiv_id or "").strip()
    if not arxiv_id:
        return {"success": False, "message": "arxiv_id is required", "paper": None}
    try:
        url = f"{ARXIV_API_URL}?id_list={urllib.parse.quote(arxiv_id)}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as response:
            root = ET.fromstring(response.read().decode("utf-8"))
        entries = root.findall("atom:entry", ARXIV_NS)
        for entry in entries:
            paper = _parse_arxiv_entry(entry)
            if paper:
                return {"success": True, "paper": paper, "source": "arxiv"}
        return {
            "success": False,
            "message": "arXiv 返回空结果",
            "paper": None,
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"arXiv 查询失败: {exc}",
            "paper": None,
        }


def _extract_keywords(title: str, max_tokens: int = 6) -> str:
    """从长问句式标题抽取核心关键词，给 Crossref 做二次检索。
    默认取 6 个 token（保留 "Vision-Language Models" 这种组合不被截断）。"""
    cleaned = re.sub(r"[^\w\s-]", " ", title or "")
    tokens = [t for t in cleaned.split() if t.lower() not in EN_STOPWORDS and len(t) > 2]
    return " ".join(tokens[:max_tokens])


def resolve_paper(
    title: Optional[str] = None,
    doi: Optional[str] = None,
    arxiv_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    三段式论文元数据解析：DOI (Crossref) → arXiv ID → 标题关键词 (Crossref)。

    返回 ``{success, paper, source, message}``。``source`` 取值：
    ``"crossref-doi"`` / ``"arxiv"`` / ``"crossref-title"`` / ``None``。
    """
    doi = (doi or "").strip()
    arxiv_id = (arxiv_id or "").strip()
    title = (title or "").strip()

    # 1) Crossref by DOI
    if doi:
        result = get_paper_by_doi(doi)
        if result.get("success") and result.get("paper"):
            result["source"] = "crossref-doi"
            return result

    # 2) arXiv by id
    if arxiv_id:
        result = fetch_arxiv_paper(arxiv_id)
        if result.get("success") and result.get("paper"):
            return result

    # 3) Crossref by title keywords（兜底，比全文搜索准）
    if title:
        keywords = _extract_keywords(title)
        if keywords:
            result = search_papers(keywords, rows=10)
            if result.get("success") and result.get("papers"):
                # 找标题前缀/包含匹配的排第一
                title_lower = title.lower()
                papers = result["papers"]
                best = papers[0]
                for p in papers:
                    pt = (p.get("title") or "").lower()
                    if pt and (title_lower.startswith(pt[:30]) or pt.startswith(title_lower[:30])):
                        best = p
                        break
                return {
                    "success": True,
                    "paper": best,
                    "source": "crossref-title",
                    "total": result.get("total", 0),
                }

    return {
        "success": False,
        "message": "未找到该论文（DOI/arXiv ID/标题关键词 均无结果）",
        "paper": None,
    }


def generate_bibtex(paper: Dict[str, Any]) -> str:
    """生成 BibTeX 格式。arXiv preprint 用 ``@misc``，期刊论文用 ``@article``。"""
    # 生成 cite key
    first_author = paper.get("authors", [{}])[0].get("family", "Unknown") if paper.get("authors") else "Unknown"
    year = paper.get("year", "")
    cite_key = f"{first_author.lower()}{year}"

    # arXiv preprint / 无期刊定位 → @misc
    is_preprint = (
        (paper.get("type") == "preprint")
        or (paper.get("journal_short", "").lower() == "arxiv")
        or not paper.get("journal")
        or paper.get("arxiv_id")
    )
    entry_type = "misc" if is_preprint else "article"

    lines = [f"@{entry_type}{{{cite_key},"]

    # 作者
    authors_list = paper.get("authors", []) or []
    authors = " and ".join(
        [f"{a['family']}, {a['given']}" for a in authors_list if a.get("family")]
    )
    if authors:
        lines.append(f"  author = {{{authors}}},")

    # 标题
    title = paper.get("title", "")
    if title:
        lines.append(f"  title = {{{title}}},")

    # 期刊（preprint 写到 howpublished）
    journal = paper.get("journal", "")
    if is_preprint:
        if paper.get("arxiv_id"):
            lines.append(f"  howpublished = {{arXiv:{paper['arxiv_id']}}},")
        elif journal:
            lines.append(f"  howpublished = {{{journal}}},")
    elif journal:
        lines.append(f"  journal = {{{journal}}},")

    # 年份
    if year:
        lines.append(f"  year = {{{year}}},")

    # 卷 / 期 / 页码（preprint 一般没有）
    if not is_preprint:
        if paper.get("volume"):
            lines.append(f"  volume = {{{paper['volume']}}},")
        if paper.get("issue"):
            lines.append(f"  number = {{{paper['issue']}}},")
        if paper.get("page"):
            lines.append(f"  pages = {{{paper['page']}}},")

    # DOI
    if paper.get("doi"):
        lines.append(f"  doi = {{{paper['doi']}}},")

    # arXiv eprint
    if is_preprint and paper.get("arxiv_id"):
        lines.append(f"  eprint = {{{paper['arxiv_id']}}},")
        # eprinttype 默认 'arXiv'，保留字段明确即可

    # URL
    if paper.get("url"):
        lines.append(f"  url = {{{paper['url']}}},")

    lines.append("}")

    return "\n".join(lines)


def generate_ris(paper: Dict[str, Any]) -> str:
    """生成 RIS 格式"""
    lines = ["TY  - JOUR"]
    
    # 作者
    for author in paper.get("authors", []):
        lines.append(f"AU  - {author['family']}, {author['given']}")
    
    # 标题
    title = paper.get("title", "")
    if title:
        lines.append(f"TI  - {title}")
    
    # 期刊
    journal = paper.get("journal", "")
    if journal:
        lines.append(f"JO  - {journal}")
        lines.append(f"T2  - {journal}")
    
    # 年份
    year = paper.get("year", "")
    if year:
        lines.append(f"PY  - {year}")
        lines.append(f"DA  - {year}")
    
    # 卷
    volume = paper.get("volume", "")
    if volume:
        lines.append(f"VL  - {volume}")
    
    # 期
    issue = paper.get("issue", "")
    if issue:
        lines.append(f"IS  - {issue}")
    
    # 页码
    page = paper.get("page", "")
    if page:
        lines.append(f"SP  - {page}")
    
    # DOI
    doi = paper.get("doi", "")
    if doi:
        lines.append(f"DO  - {doi}")
    
    # URL
    url = paper.get("url", "")
    if url:
        lines.append(f"UR  - {url}")
    
    lines.append("ER  - ")
    
    return "\n".join(lines)


# CLI 测试
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python citation_service.py <action> [params]")
        print("Actions: search, cite, generate, resolve")
        sys.exit(1)

    action = sys.argv[1]

    if action == "search" and len(sys.argv) > 2:
        query = sys.argv[2]
        result = search_papers(query, 10)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "resolve" and len(sys.argv) > 2:
        # argv[2] 是 JSON payload（含 title/doi/arxiv_id）
        try:
            payload = json.loads(sys.argv[2])
        except json.JSONDecodeError as exc:
            print(json.dumps({"success": False, "message": f"JSON 解析错误: {exc}"}))
            sys.exit(0)
        result = resolve_paper(
            doi=payload.get("doi"),
            arxiv_id=payload.get("arxiv_id"),
            title=payload.get("title"),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif action == "cite" and len(sys.argv) > 2:
        doi = sys.argv[2]
        result = get_paper_by_doi(doi)
        if result["success"]:
            paper = result["paper"]
            print("APA:")
            print(generate_citation(paper, "apa"))
            print("\nMLA:")
            print(generate_citation(paper, "mla"))
            print("\nGB/T 7714:")
            print(generate_citation(paper, "gb7714"))
            print("\nBibTeX:")
            print(generate_citation(paper, "bibtex"))
        else:
            print(f"Error: {result['message']}")
    
    elif action == "generate" and len(sys.argv) > 2:
        # 从 JSON 字符串解析 paper 数据
        paper_json = sys.argv[2]
        try:
            paper = json.loads(paper_json)
            citations = {
                "apa": generate_citation(paper, "apa"),
                "mla": generate_citation(paper, "mla"),
                "chicago": generate_citation(paper, "chicago"),
                "gb7714": generate_citation(paper, "gb7714"),
                "bibtex": generate_citation(paper, "bibtex"),
                "ris": generate_citation(paper, "ris"),
            }
            result = {
                "success": True,
                "citations": citations
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except json.JSONDecodeError as e:
            print(json.dumps({
                "success": False,
                "message": f"JSON 解析错误: {str(e)}"
            }))
    
    else:
        print(f"Unknown action: {action}")