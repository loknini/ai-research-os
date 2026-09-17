#!/usr/bin/env python3
"""RAG 2.1 correctness regression: isolation, generations, full-corpus recall and leases."""
from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="rag_v21_qa_"))
os.environ["DATA_DIR"] = str(TMP)

# Seed the exact 2.0-style global-primary-key tables to exercise in-place migration.
with sqlite3.connect(TMP / "ai_research_os.db") as legacy:
    legacy.executescript('''
        CREATE TABLE rag_sources (
            id TEXT PRIMARY KEY, space_id TEXT NOT NULL DEFAULT '__default__', name TEXT,
            kind TEXT DEFAULT 'local', target_paths TEXT, recursive INTEGER DEFAULT 1,
            file_types TEXT, status TEXT DEFAULT 'pending', doc_count INTEGER DEFAULT 0,
            chunk_count INTEGER DEFAULT 0, progress INTEGER DEFAULT 0,
            total_files INTEGER DEFAULT 0, embedding_model TEXT,
            embed_mode TEXT DEFAULT 'keyword', error TEXT, created_at INTEGER, updated_at INTEGER);
        CREATE TABLE rag_documents (
            id TEXT PRIMARY KEY, space_id TEXT NOT NULL DEFAULT '__default__', source_id TEXT,
            file_path TEXT, file_name TEXT, file_type TEXT, file_size INTEGER,
            page_count INTEGER, char_count INTEGER, chunk_count INTEGER, url TEXT,
            title TEXT, section TEXT, content_hash TEXT, fetched_at INTEGER, created_at INTEGER);
        CREATE TABLE rag_chunks (
            id TEXT PRIMARY KEY, space_id TEXT NOT NULL DEFAULT '__default__', source_id TEXT,
            doc_id TEXT, chunk_index INTEGER, content TEXT, page_start INTEGER, page_end INTEGER,
            char_start INTEGER, char_end INTEGER, embedding TEXT, token_count INTEGER,
            created_at INTEGER);
    ''')

from scripts import database  # noqa: E402
from backend.server import rag_service  # noqa: E402


async def main() -> None:
    await database.init_db()

    # Same system IDs must coexist in different spaces.
    for space in ("alpha", "beta"):
        assert await database.ensure_rag_source(
            "__papers__", space, "papers", kind="paper")
        assert await database.ensure_rag_source(
            "__web__", space, "web", kind="web")
    assert len(await database.get_rag_sources("alpha")) == 2
    assert len(await database.get_rag_sources("beta")) == 2
    print("PASS composite space identity")

    space = "alpha"
    source = "atomic-source"
    assert await database.create_rag_source(
        source, space, "atomic", [], True, ["txt"], status="ready")
    await database.update_rag_source(source, space, active_generation_id="old")
    assert await database.create_rag_document(
        "old-doc", space, source, "old.txt", "old.txt", "txt",
        generation_id="old")
    await database.insert_rag_chunks([{
        "id": "old-chunk", "source_id": source, "doc_id": "old-doc",
        "content": "obsoleteonly visible", "generation_id": "old",
    }], space)
    assert await database.create_rag_document(
        "new-doc", space, source, "new.txt", "new.txt", "txt",
        generation_id="new")
    await database.insert_rag_chunks([{
        "id": "new-chunk", "source_id": source, "doc_id": "new-doc",
        "content": "new generation staged", "generation_id": "new",
    }], space)
    before = await database.get_rag_chunks_for_retrieval(space, [source])
    assert [x["id"] for x in before] == ["old-chunk"]
    assert await database.activate_rag_generation(
        source, space, "new", status="ready", doc_count=1, chunk_count=1,
        embed_mode="keyword")
    after = await database.get_rag_chunks_for_retrieval(space, [source])
    assert [x["id"] for x in after] == ["new-chunk"]
    await database.clear_rag_generation(source, space, "new", keep=True)
    assert not await database.fts_search_chunk_ids(space, "obsoleteonly", source_ids=[source])
    print("PASS atomic generation activation + FTS cleanup")

    assert await database.acquire_rag_worker_lease("worker-a", 60)
    assert not await database.acquire_rag_worker_lease("worker-b", 60)
    assert await database.release_rag_worker_lease("worker-a")
    assert await database.acquire_rag_worker_lease("worker-b", 60)
    await database.release_rag_worker_lease("worker-b")
    print("PASS global single-writer lease")

    # The unique hit lives beyond the old arbitrary 3000-row boundary.
    bulk = "bulk-source"
    assert await database.create_rag_source(
        bulk, space, "bulk", [], True, ["txt"], status="ready")
    await database.update_rag_source(bulk, space, active_generation_id="g1")
    assert await database.create_rag_document(
        "bulk-doc", space, bulk, "bulk.txt", "bulk.txt", "txt",
        generation_id="g1")
    rows = []
    for i in range(3105):
        rows.append({
            "id": f"bulk-{i}", "source_id": bulk, "doc_id": "bulk-doc",
            "content": ("ordinary filler" if i < 3104 else "ultraunique tail evidence"),
            "generation_id": "g1",
        })
        if len(rows) == 200:
            assert await database.insert_rag_chunks(rows, space) == len(rows)
            rows = []
    assert await database.insert_rag_chunks(rows, space) == len(rows)
    hits, mode, _, _ = await rag_service.retrieve(
        space, "ultraunique tail evidence", top_k=1, source_ids=[bulk])
    assert hits and hits[0]["chunkId"] == "bulk-3104", (mode, hits[:1])
    print("PASS full-corpus candidate retrieval (>3000 rows)")

    for unsafe in ("http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/"):
        try:
            rag_service._assert_public_web_url(unsafe)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"SSRF URL accepted: {unsafe}")
    assert rag_service.normalize_url("http://user:pass@example.com/") == ""
    print("PASS SSRF guards")

    paper_job = await database.enqueue_rag_job(
        space, "__papers__", "paper_index", {"paper_id": "p1"},
        dedupe_key="paper:p1")
    web_job = await database.enqueue_rag_job(
        space, "__web__", "web_index", {"urls": ["https://example.com/"]},
        dedupe_key="web:example")
    assert paper_job != web_job
    print("PASS unified persistent queue kinds")
    print("ALL_RAG_V21_QA_PASS")


if __name__ == "__main__":
    asyncio.run(main())
