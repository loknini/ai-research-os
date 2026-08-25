#!/usr/bin/env python3
"""
Citation Service - 参考文献引用生成服务
使用 Crossref API 获取论文元数据并生成各种引用格式
"""

import os
import sys
import json
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
    通过 Crossref API 搜索论文
    
    Args:
        query: 搜索关键词（标题、作者、DOI 等）
        rows: 返回结果数量
    
    Returns:
        {
            "success": True/False,
            "papers": [...],
            "message": "错误信息"
        }
    """
    try:
        # 构建查询 URL
        encoded_query = urllib.parse.quote(query)
        url = f"{CROSSREF_API_BASE}/works?query={encoded_query}&rows={rows}&sort=relevance&order=desc"
        
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


def generate_bibtex(paper: Dict[str, Any]) -> str:
    """生成 BibTeX 格式"""
    # 生成 cite key
    first_author = paper.get("authors", [{}])[0].get("family", "Unknown")
    year = paper.get("year", "")
    cite_key = f"{first_author.lower()}{year}"
    
    lines = [f"@article{{{cite_key},"]
    
    # 作者
    authors = " and ".join([f"{a['family']}, {a['given']}" for a in paper.get("authors", [])])
    if authors:
        lines.append(f"  author = {{{authors}}},")
    
    # 标题
    title = paper.get("title", "")
    if title:
        lines.append(f"  title = {{{title}}},")
    
    # 期刊
    journal = paper.get("journal", "")
    if journal:
        lines.append(f"  journal = {{{journal}}},")
    
    # 年份
    if year:
        lines.append(f"  year = {{{year}}},")
    
    # 卷
    volume = paper.get("volume", "")
    if volume:
        lines.append(f"  volume = {{{volume}}},")
    
    # 期
    issue = paper.get("issue", "")
    if issue:
        lines.append(f"  number = {{{issue}}},")
    
    # 页码
    page = paper.get("page", "")
    if page:
        lines.append(f"  pages = {{{page}}},")
    
    # DOI
    doi = paper.get("doi", "")
    if doi:
        lines.append(f"  doi = {{{doi}}},")
    
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
        print("Actions: search, cite, generate")
        sys.exit(1)
    
    action = sys.argv[1]
    
    if action == "search" and len(sys.argv) > 2:
        query = sys.argv[2]
        result = search_papers(query, 10)
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