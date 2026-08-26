#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression coverage for the confirmed correctness fixes (network-free)."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = Path(tempfile.mkdtemp(prefix="qa_correctness_"))
os.environ["DATA_DIR"] = str(TMP_DIR)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import database  # noqa: E402

database.DATA_DIR = TMP_DIR
database.DB_PATH = TMP_DIR / "ai_research_os.db"

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    CHECKS.append((name, condition, detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def paper(arxiv_id: str, *, paper_id: str | None = None) -> dict:
    return {
        "id": paper_id or arxiv_id,
        "title": f"Paper {arxiv_id}",
        "authors": ["QA"],
        "abstract": "offline fixture",
        "arxivId": arxiv_id,
        "pdfUrl": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        "categories": ["cs.AI"],
        "publishedDate": "2026-01-01",
        "tags": [],
        "addedAt": 1,
    }


async def downgrade_papers_to_legacy() -> None:
    """Turn the current table into the old global-UNIQUE shape for migration QA."""
    async with database.get_db() as conn:
        await conn.commit()
        await conn.execute("PRAGMA foreign_keys=OFF")
        await conn.execute("BEGIN IMMEDIATE")
        await conn.execute("""
            CREATE TABLE papers_legacy (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors TEXT NOT NULL,
                abstract TEXT NOT NULL,
                arxiv_id TEXT UNIQUE NOT NULL,
                pdf_url TEXT NOT NULL,
                categories TEXT,
                published_date TEXT NOT NULL,
                local_path TEXT,
                summary TEXT,
                bibtex TEXT,
                tags TEXT,
                is_read INTEGER DEFAULT 0,
                is_favorite INTEGER DEFAULT 0,
                added_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                space_id TEXT NOT NULL DEFAULT '__default__'
            )
        """)
        await conn.execute("INSERT INTO papers_legacy SELECT * FROM papers")
        await conn.execute("DROP TABLE papers")
        await conn.execute("ALTER TABLE papers_legacy RENAME TO papers")
        await conn.execute(
            "CREATE INDEX idx_papers_custom_title_date ON papers(title, published_date)"
        )
        await conn.commit()
        await conn.execute("PRAGMA foreign_keys=ON")


def run_parallel_database_cli() -> None:
    env = os.environ.copy()
    env["DATA_DIR"] = str(TMP_DIR)
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "scripts.database"],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for _ in range(4)
    ]
    results = [process.communicate(timeout=60) + (process.returncode,) for process in processes]
    ok = all(code == 0 and "Database initialized at" in stdout for stdout, _stderr, code in results)
    detail = "; ".join(f"exit={code}, stderr={stderr.strip()[:80]}" for _out, stderr, code in results)
    check("旧库可多进程并发、幂等初始化", ok, detail)


async def verify_paper_migration() -> None:
    await database.init_db()
    inserted = await database.insert_paper(paper("2601.00001", paper_id="legacy-paper"), "alpha")
    note_ok = await database.insert_note({
        "id": "linked-note",
        "title": "linked",
        "content": "kept",
        "paperId": "legacy-paper",
    }, "alpha")
    check("迁移夹具已写入论文与关联笔记", inserted and note_ok)
    await downgrade_papers_to_legacy()

    run_parallel_database_cli()
    await database.init_db()
    await database.init_db()

    async with database.get_db() as conn:
        index_rows = await (await conn.execute("PRAGMA index_list(papers)")).fetchall()
        unique_sets = []
        for row in index_rows:
            if row["unique"]:
                cols = await (await conn.execute(f'PRAGMA index_info("{row["name"]}")')).fetchall()
                unique_sets.append(tuple(col["name"] for col in cols))
        note = await (await conn.execute(
            "SELECT paper_id FROM notes WHERE id = 'linked-note'"
        )).fetchone()
        violations = await (await conn.execute("PRAGMA foreign_key_check")).fetchall()
        index_names = {row["name"] for row in index_rows}
    check("论文唯一性迁为 (space_id, arxiv_id)", ("space_id", "arxiv_id") in unique_sets)
    check("旧全局 arxiv_id UNIQUE 已移除", ("arxiv_id",) not in unique_sets)
    check("迁移保留论文 ID 与笔记外键", note is not None and note["paper_id"] == "legacy-paper")
    check("迁移后 foreign_key_check 通过", not violations, str(violations))

    check("论文迁移保留既有自定义索引", "idx_papers_custom_title_date" in index_names)

    same_space = await database.insert_paper(paper("2601.00001"), "alpha")
    other_space = await database.insert_paper(paper("2601.00001"), "beta")
    beta = await database.get_paper_by_arxiv("2601.00001", "beta")
    expected_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL, "ai-research-os://papers/beta/2601.00001"
    ))
    check("同空间按 arxivId 去重", same_space is False)
    check("跨空间可插入同一 arXiv", other_space is True)
    check("官方抓取 ID 按空间确定且不透明", beta is not None and beta["id"] == expected_id)


async def verify_cron() -> None:
    from backend.server import cron_scheduler
    from backend.server.routers import cron as cron_router
    from scripts import fetch_arxiv

    now = int(time.time() * 1000)
    job = await database.create_cron_job({
        "id": "claim-job",
        "name": "claim",
        "schedule": "* * * * *",
        "command": f'"{sys.executable}" -c "print(123)"',
        "jobType": "command",
    }, "alpha")
    due = now - 1000
    following = now + 60000
    async with database.get_db() as conn:
        await conn.execute("UPDATE cron_jobs SET next_run = ? WHERE id = ?", (due, job["id"]))
    claims = await asyncio.gather(*[
        database.try_acquire_cron_job(job["id"], "alpha", due, now, following)
        for _ in range(8)
    ])
    stale = await database.try_acquire_cron_job(job["id"], "alpha", due, now + 1, following + 1)
    claimed = await database.get_cron_jobs("alpha")
    claimed_job = next(item for item in claimed if item["id"] == job["id"])
    check("Cron 首次 last_run=NULL 仍可领取", any(claims))
    check("Cron 并发仅一个 Worker 领取", sum(bool(value) for value in claims) == 1, str(claims))
    check("Cron 旧 next_run 快照被拒绝", stale is False)
    check("Cron 原子推进游标并计数", claimed_job["nextRun"] == following and claimed_job["runCount"] == 1)

    for index in range(55):
        await database.add_cron_run_history(
            f"noise-{index}", "noise-job", "alpha", "success", "noise",
            now + index, now + index, 0,
        )
    await database.add_cron_run_history(
        "target-history", job["id"], "alpha", "success", "target",
        now - 10000, now - 10000, 0,
    )
    filtered = await database.get_cron_run_history("alpha", 50, cron_job_id=job["id"])
    check("Cron 历史先按任务过滤再 LIMIT", [row["id"] for row in filtered] == ["target-history"])

    arxiv_job = await database.create_cron_job({
        "id": "manual-arxiv",
        "name": "manual arxiv",
        "description": "fixture",
        "schedule": "daily",
        "command": "",
        "jobType": "arxiv_fetch",
        "payload": {"query": "cat:cs.AI", "keywords": ["offline"], "max": 2, "days": 1},
    }, "alpha")
    fixed_next = now + 999999
    async with database.get_db() as conn:
        await conn.execute("UPDATE cron_jobs SET next_run = ? WHERE id = ?", (fixed_next, arxiv_job["id"]))

    original_fetch = fetch_arxiv.fetch_papers
    fetch_arxiv.fetch_papers = lambda **_kwargs: [paper("2601.99999")]
    try:
        result = await cron_router.run_job(arxiv_job["id"], space_id="alpha")
    finally:
        fetch_arxiv.fetch_papers = original_fetch
    saved = await database.get_paper_by_arxiv("2601.99999", "alpha")
    history = await database.get_cron_run_history("alpha", cron_job_id=arxiv_job["id"])
    refreshed = next(item for item in await database.get_cron_jobs("alpha") if item["id"] == arxiv_job["id"])
    check("手动 arXiv 与自动执行共用分派并落库", result["status"] == "success" and saved is not None)
    check("手动 Cron 执行写历史", len(history) == 1 and history[0]["status"] == "success")
    check("手动 Cron 不推进原 next_run", refreshed["nextRun"] == fixed_next)
    status, output = await cron_scheduler.execute_job({
        "id": "bad-arxiv", "jobType": "arxiv_fetch", "payload": {"max": 0}
    }, "alpha")
    check("Cron 参数校验返回明确错误", status == "error" and "max" in output, output)


    invalid_create = await cron_router.create_job(cron_router.JobCreate(
        name="invalid", schedule="not a schedule", enabled=False
    ), space_id="alpha")
    check("禁用 Cron 也拒绝非法计划", invalid_create.status_code == 400)

    await database.create_cron_job({
        "id": "legacy-invalid", "name": "legacy invalid", "schedule": "not a schedule",
        "command": "echo never", "enabled": False,
    }, "alpha")
    invalid_toggle = await cron_router.toggle_job("legacy-invalid", space_id="alpha")
    legacy_invalid = next(
        item for item in await database.get_cron_jobs("alpha") if item["id"] == "legacy-invalid"
    )
    check(
        "非法旧 Cron 无法启用且状态不变",
        invalid_toggle.status_code == 400 and legacy_invalid["enabled"] is False,
    )


async def verify_api_and_writes() -> None:
    from fastapi.testclient import TestClient
    from backend.server.main import app
    from backend.server.routers import formula as formula_router

    await database.create_version("note", "linked-note", {"title": "v1"}, space_id="alpha")
    versions = await database.get_versions("note", "linked-note", space_id="alpha")
    version_id = versions[0]["id"]

    now = int(time.time() * 1000)
    async with database.get_db() as conn:
        await conn.execute("""
            INSERT INTO formula_history
            (id, latex_code, confidence, source_type, is_favorite, tags, note, created_at, space_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("formula-1", "x", 1.0, "upload", 0, "[]", "", now, "alpha"))

    with TestClient(app) as client:
        headers = {"X-Space-Key": "alpha"}
        detail = client.get(f"/api/versions/detail/{version_id}", headers=headers)
        check("版本详情路由命中详情处理器", detail.status_code == 200 and detail.json().get("version", {}).get("id") == version_id)

        flat = client.put("/api/formula/history", headers=headers, json={
            "id": "formula-1", "isFavorite": True, "tags": ["qa"], "note": "flat"
        })
        legacy = client.put("/api/formula/history", headers=headers, json={
            "recordId": "formula-1", "updates": {"is_favorite": False, "note": "legacy"}
        })
        missing_update = client.put("/api/formula/history", headers=headers, json={
            "id": "formula-missing", "note": "none"
        })
        missing_delete = client.delete("/api/formula/history/formula-missing", headers=headers)
        deleted = client.delete("/api/formula/history/formula-1", headers=headers)
        original_run_script = formula_router.run_script
        formula_router.run_script = lambda *_args, **_kwargs: {
            "success": False, "updated": False, "error": "UPDATE_FAILED"
        }
        try:
            failed_update = client.put("/api/formula/history", headers=headers, json={
                "id": "formula-1", "note": "db failure"
            })
        finally:
            formula_router.run_script = original_run_script
        check("公式规范平铺更新成功", flat.status_code == 200 and flat.json().get("updated") is True)
        check("公式旧嵌套更新继续兼容", legacy.status_code == 200 and legacy.json().get("updated") is True)
        check("公式不存在更新返回 404", missing_update.status_code == 404)
        check("公式不存在删除返回 404", missing_delete.status_code == 404)
        check("公式真实删除成功", deleted.status_code == 200 and deleted.json().get("deleted") is True)

        check("公式数据库异常不误报 404", failed_update.status_code == 500)

    created = await database.create_rag_document(
        "rag-1", "alpha", "source-1", "fixture.txt", "fixture.txt", "txt"
    )
    updated = await database.update_rag_document("rag-1", "alpha", 3)
    missing = await database.update_rag_document("rag-missing", "alpha", 3)
    check("RAG 更新返回真实 rowcount", created and updated and missing is False)


def verify_clis() -> None:
    env = os.environ.copy()
    env["DATA_DIR"] = str(TMP_DIR)
    database_cli = subprocess.run(
        [sys.executable, "-m", "scripts.database"], cwd=PROJECT_ROOT, env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    check("database 模块 CLI 真正调用 _main", database_cli.returncode == 0 and "Database initialized at" in database_cli.stdout)

    direct = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "backend/server/agent_service.py")],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    )
    module = subprocess.run(
        [sys.executable, "-m", "backend.server.agent_service", "roles"],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    )
    check("Agent 文件直跑给出模块用法", direct.returncode == 2 and "python -m backend.server.agent_service" in direct.stderr)
    check("Agent 模块 CLI 保持可用", module.returncode == 0 and "architect" in module.stdout)


async def main() -> int:
    try:
        await verify_paper_migration()
        await verify_cron()
        await verify_api_and_writes()
        verify_clis()
    finally:
        from backend.server.cron_scheduler import stop_scheduler
        stop_scheduler()

    failed = [name for name, ok, _detail in CHECKS if not ok]
    print(f"\nCorrectness QA: {len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
    if failed:
        print("Failed: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
