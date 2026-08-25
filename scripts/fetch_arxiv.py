#!/usr/bin/env python3
"""
ArXiv Paper Fetcher Script
Fetches papers from arXiv API and saves metadata locally.
"""
from __future__ import annotations

import sys
import json
import asyncio
import urllib.request
import urllib.parse
import os
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET
from pathlib import Path

# 导入数据库模块（已改为 aiosqlite 异步；此处仅取常量与协程函数，调用处 await）。
sys.path.insert(0, str(Path(__file__).parent))
import database

# 归档命名空间：PDF 落到 data/papers/<space_id>/pdfs/（见 space-key 软隔离约定）。
from database import DEFAULT_SPACE

# Constants
ARXIV_API_URL = "http://export.arxiv.org/api/query"
DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"
MAX_RESULTS = 50


def fetch_papers(
    search_query: str = "cat:cs.CV",
    keywords: list = None,
    start_date: str = None,
    end_date: str = None,
    max_results: int = 10
) -> list:
    """Fetch papers from arXiv API (synchronous; no DB writes)."""
    # Build base query
    base_query = search_query

    # Add keywords if provided
    if keywords and len(keywords) > 0:
        keyword_query = " OR ".join([f"all:{kw}" for kw in keywords])
        base_query = f"({base_query}) AND ({keyword_query})"

    # Build query parameters
    params = {
        "search_query": base_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    }

    # Add date filter if provided
    if start_date and end_date:
        date_query = f"[{start_date} TO {end_date}]"
        params["search_query"] = f"({base_query}) AND submittedDate:{date_query}"

    query_string = urllib.parse.urlencode(params)
    url = f"{ARXIV_API_URL}?{query_string}"

    print(f"Fetching papers from: {url}", file=sys.stderr)

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "AI-Research-OS/0.1 (Research Paper Fetcher)"
            }
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read().decode('utf-8')

        # Parse XML
        root = ET.fromstring(data)

        # Define namespace
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'arxiv': 'http://arxiv.org/schemas/atom'
        }

        papers = []

        for entry in root.findall('atom:entry', ns):
            paper = parse_entry(entry, ns)
            if paper:
                papers.append(paper)

        return papers

    except Exception as e:
        print(f"Error fetching papers: {e}", file=sys.stderr)
        return []


def parse_entry(entry, ns) -> dict:
    """Parse a single arXiv entry."""
    try:
        id_elem = entry.find('atom:id', ns)
        if id_elem is None:
            return None

        arxiv_url = id_elem.text
        arxiv_id = arxiv_url.split('/abs/')[-1] if '/abs/' in arxiv_url else arxiv_url

        title_elem = entry.find('atom:title', ns)
        title = title_elem.text.strip() if title_elem is not None else "Unknown"

        authors = []
        for author in entry.findall('atom:author', ns):
            name = author.find('atom:name', ns)
            if name is not None:
                authors.append(name.text)

        summary_elem = entry.find('atom:summary', ns)
        abstract = summary_elem.text.strip() if summary_elem is not None else ""

        published_elem = entry.find('atom:published', ns)
        published = published_elem.text[:10] if published_elem is not None else datetime.now().strftime('%Y-%m-%d')

        categories = []
        for cat in entry.findall('atom:category', ns):
            term = cat.get('term')
            if term:
                categories.append(term)

        primary_cat = entry.find('arxiv:primary_category', ns)
        if primary_cat is not None:
            primary_term = primary_cat.get('term')
            if primary_term and primary_term not in categories:
                categories.insert(0, primary_term)

        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        return {
            "id": arxiv_id,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "arxivId": arxiv_id,
            "pdfUrl": pdf_url,
            "categories": categories[:5],
            "publishedDate": published,
            "localPath": None,
            "summary": None,
            "tags": [],
            "isRead": False,
            "isFavorite": False,
            "addedAt": int(datetime.now().timestamp() * 1000)
        }

    except Exception as e:
        print(f"Error parsing entry: {e}", file=sys.stderr)
        return None


def load_existing_metadata(data_dir: Path) -> dict:
    """Load existing paper metadata."""
    metadata_file = data_dir / "papers" / "metadata.json"

    if metadata_file.exists():
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading metadata: {e}", file=sys.stderr)

    return {"papers": [], "lastUpdated": None}


def save_metadata(data_dir: Path, metadata: dict):
    """Save paper metadata."""
    papers_dir = data_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    metadata_file = papers_dir / "metadata.json"

    try:
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"Metadata saved to: {metadata_file}", file=sys.stderr)
    except Exception as e:
        print(f"Error saving metadata: {e}", file=sys.stderr)


def download_pdf(arxiv_id: str, pdf_url: str, data_dir: Path, space_id: str = DEFAULT_SPACE) -> str:
    """Download PDF file into ``data/papers/<space_id>/pdfs/`` namespace.

    Args:
        arxiv_id: The arXiv id used as the file name.
        pdf_url: The PDF download URL.
        data_dir: Project data root (``DATA_DIR``).
        space_id: Space key used for filesystem isolation.

    Returns:
        Local path to the downloaded PDF, or ``None`` on failure.
    """
    # 按空间归档：data/papers/<space_id>/pdfs/<arxiv_id>.pdf
    pdfs_dir = data_dir / "papers" / space_id / "pdfs"
    pdfs_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = pdfs_dir / f"{arxiv_id}.pdf"

    if pdf_path.exists():
        print(f"PDF already exists: {pdf_path}", file=sys.stderr)
        return str(pdf_path)

    try:
        print(f"Downloading PDF: {pdf_url}", file=sys.stderr)
        req = urllib.request.Request(
            pdf_url,
            headers={"User-Agent": "AI-Research-OS/0.1"}
        )

        with urllib.request.urlopen(req, timeout=60) as response:
            with open(pdf_path, 'wb') as f:
                f.write(response.read())

        print(f"PDF saved to: {pdf_path}", file=sys.stderr)
        return str(pdf_path)

    except Exception as e:
        print(f"Error downloading PDF: {e}", file=sys.stderr)
        return None


async def main():
    """Main entry point (async — DB layer is aiosqlite)."""
    # Parse arguments
    if len(sys.argv) < 2:
        print("Usage: fetch_arxiv.py <command> [options]", file=sys.stderr)
        print("Commands: fetch, download", file=sys.stderr)
        sys.exit(1)

    # 初始化数据库（幂等：补 space_id 列 + 索引 + WAL）。
    await database.init_db()

    command = sys.argv[1]

    # Get data directory from environment or use default
    data_dir = Path(os.environ.get('DATA_DIR', DEFAULT_DATA_DIR))

    if command == "fetch":
        search_query = "cat:cs.CV"
        keywords = []
        max_results = 10
        download_pdfs = False
        days_back = 1

        i = 2
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == "--query" and i + 1 < len(sys.argv):
                search_query = sys.argv[i + 1]
                i += 2
            elif arg == "--keywords" and i + 1 < len(sys.argv):
                keywords_str = sys.argv[i + 1]
                keywords = [kw.strip() for kw in keywords_str.split(',') if kw.strip()]
                i += 2
            elif arg == "--max" and i + 1 < len(sys.argv):
                max_results = int(sys.argv[i + 1])
                i += 2
            elif arg == "--days" and i + 1 < len(sys.argv):
                days_back = int(sys.argv[i + 1])
                i += 2
            elif arg == "--download":
                download_pdfs = True
                i += 1
            else:
                i += 1

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)

        keyword_str = f" with keywords: {', '.join(keywords)}" if keywords else ""
        print(f"Fetching up to {max_results} papers from last {days_back} day(s){keyword_str}...", file=sys.stderr)

        papers = fetch_papers(
            search_query=search_query,
            keywords=keywords if keywords else None,
            start_date=start_date.strftime('%Y%m%d'),
            end_date=end_date.strftime('%Y%m%d'),
            max_results=max_results
        )

        if not papers:
            print(json.dumps({"success": False, "message": "No papers found", "papers": []}))
            sys.exit(0)

        new_papers = []
        for paper in papers:
            existing = await database.get_paper_by_arxiv(paper["arxivId"], space_id=DEFAULT_SPACE)
            if not existing:
                if download_pdfs:
                    local_path = download_pdf(paper["arxivId"], paper["pdfUrl"], data_dir, space_id=DEFAULT_SPACE)
                    paper["localPath"] = local_path
                if await database.insert_paper(paper, space_id=DEFAULT_SPACE):
                    new_papers.append(paper)

        total_count = await database.get_papers_count(space_id=DEFAULT_SPACE)

        result = {
            "success": True,
            "message": f"Fetched {len(new_papers)} new papers (skipped {len(papers) - len(new_papers)} duplicates)",
            "papers": new_papers,
            "total": total_count
        }

        print(json.dumps(result, indent=2))

    elif command == "list":
        from database import get_all_papers

        limit = 20
        for i, arg in enumerate(sys.argv[2:], 2):
            if arg == "--limit" and i + 1 < len(sys.argv):
                limit = int(sys.argv[i + 1])

        papers = await get_all_papers(space_id=DEFAULT_SPACE, limit=limit)
        total = await database.get_papers_count(space_id=DEFAULT_SPACE)

        print(json.dumps({
            "success": True,
            "papers": papers,
            "total": total,
            "lastUpdated": datetime.now().isoformat()
        }, indent=2))

    elif command == "download":
        if len(sys.argv) < 3:
            print("Usage: fetch_arxiv.py download <arxiv_id>", file=sys.stderr)
            sys.exit(1)

        arxiv_id = sys.argv[2]
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        local_path = download_pdf(arxiv_id, pdf_url, data_dir, space_id=DEFAULT_SPACE)

        if local_path:
            metadata = load_existing_metadata(data_dir)
            for paper in metadata.get("papers", []):
                if paper["arxivId"] == arxiv_id:
                    paper["localPath"] = local_path
                    break
            save_metadata(data_dir, metadata)

            print(json.dumps({"success": True, "path": local_path}))
        else:
            print(json.dumps({"success": False, "message": "Failed to download PDF"}))

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
