#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI-Research-OS — space-key 软隔离 独立验证脚本（QA 第二轮，fresh eyes）。

不 mock 任何隔离逻辑，直接对真实代码行为做断言：
  * 数据库层用真实 aiosqlite 连接（同源 scripts/database.py）
  * HTTP 层用 FastAPI TestClient 真实驱动 lifespan + 路由 + get_space_id 依赖

覆盖验收点：
  A. 空间隔离（跨空间 读/改/删 均被过滤/拒绝）
  B. 缺失/非法 X-Space-Key → 400；settings/health/backup 系统路由豁免
  C. 并发 ≥20 路并行写入，零 "database is locked"
  D. 向后兼容：存量无 space_id 数据归 __default__ 且可访问；cron JSON 仅迁移一次
  E. WAL：连接后 journal_mode = wal
  F. aiosqlite 连接不跨协程共享（get_db 每次新建连接）
  G. 前端 X-Space-Key 注入唯一性（仅 apiMonitor.ts 真正注入请求头）
  H. 结构：SPACE_TABLES 中 25 张迁移表均含 space_id 列 + 索引

最小侵入：脚本置于 scripts/，不影响主流程；使用隔离临时 DATA_DIR，不触碰真实 data/。
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# 0. 路径与隔离环境准备（必须在 import database / backend 之前完成）
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent          # .../scripts
PROJECT_ROOT = SCRIPT_DIR.parent                      # .../ai-research-os

TMP = Path(tempfile.mkdtemp(prefix="qa_space_"))
os.environ["DATA_DIR"] = str(TMP)                      # 隔离测试库，不污染真实 data/

# 仅把项目根与 scripts 目录加入 sys.path。
# 注意：不要把 backend/ 单独加入 sys.path —— 否则 `import scripts` 会被 backend/scripts/
# （同样叫 scripts 的包）遮蔽，导致 `from scripts import database` 解析到 backend/scripts。
# PROJECT_ROOT 在路径上即可同时解析 `backend.server`（包）与 `scripts`（包）。
for _p in (str(PROJECT_ROOT), str(SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import aiosqlite  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from scripts import database  # noqa: E402  (scripts/database.py，与后端同一模块对象)

# 强制测试库落点，必须在 import backend 之前，避免 backend 缓存真实库路径
database.DB_PATH = TMP / "ai_research_os.db"

from backend.server.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# 极简测试账本
# ---------------------------------------------------------------------------
RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    return ok


# ---------------------------------------------------------------------------
# B. HTTP 层：400 / 豁免（真实驱动 get_space_id 依赖）
# ---------------------------------------------------------------------------
def test_http_400_and_exemption() -> None:
    with TestClient(app) as client:
        # --- 缺失 X-Space-Key 的数据路由 → 400 ---
        r = client.get("/api/papers")
        record("B1 数据路由缺失 key → 400", r.status_code == 400,
               f"status={r.status_code}")

        # --- 空 key → 400 ---
        r = client.get("/api/papers", headers={"X-Space-Key": ""})
        record("B2 空 key → 400", r.status_code == 400, f"status={r.status_code}")

        # --- 过短 key (<4) → 400 ---
        r = client.get("/api/papers", headers={"X-Space-Key": "ab"})
        record("B3 key 长度<4 → 400", r.status_code == 400, f"status={r.status_code}")

        # --- 合法 key → 200 ---
        r = client.get("/api/papers", headers={"X-Space-Key": "abcd"})
        record("B4 合法 key → 200", r.status_code == 200, f"status={r.status_code}")

        # --- 系统路由豁免（不带 key 也不应 400）---
        r = client.get("/api/healthz")
        record("B5 healthz 豁免（无 key 非 400）", r.status_code != 400,
               f"status={r.status_code}")

        r = client.get("/api/settings/llm")
        record("B6 settings 豁免（无 key 非 400）", r.status_code != 400,
               f"status={r.status_code}")

        r = client.post("/api/backup/export")
        record("B7 backup 豁免（无 key 非 400）", r.status_code != 400,
               f"status={r.status_code}")


# ---------------------------------------------------------------------------
# 异步 DB 层测试：A / C / E / F / H + D(向后兼容)
# ---------------------------------------------------------------------------
def make_paper(i: int, space: str) -> dict:
    return {
        "id": f"p{i}",
        "title": f"Paper {i} in {space}",
        "abstract": f"abstract {i}",
        "arxivId": f"arxiv{i}.v1",
        "pdfUrl": f"http://x/{i}.pdf",
        "publishedDate": "2024-01-01",
        "addedAt": i,
    }


async def test_isolation() -> None:
    # 在 alpha 空间写入一条数据
    ok = await database.insert_paper(make_paper(1, "alpha"), space_id="alpha")
    if not record("A0 写入 alpha 空间成功", ok):
        return

    # 同空间可读
    mine = await database.get_all_papers(space_id="alpha")
    visible = any(p["id"] == "p1" for p in mine)
    record("A1 alpha 空间可读自身数据", visible, f"count={len(mine)}")

    # 跨空间不可见
    others = await database.get_all_papers(space_id="beta")
    hidden = not any(p["id"] == "p1" for p in others)
    record("A2 beta 空间不可见 alpha 数据", hidden, f"count={len(others)}")

    # 跨空间不可改
    changed = await database.update_paper("p1", {"title": "hacked"}, space_id="beta")
    record("A3 beta 不能修改 alpha 数据", changed is False, f"update_returned={changed}")

    # 跨空间不可删
    deleted = await database.delete_paper("p1", space_id="beta")
    record("A4 beta 不能删除 alpha 数据", deleted is False, f"delete_returned={deleted}")

    # 跨空间改/删被拒后，数据仍完好（alpha 仍可见）
    still_there = await database.get_paper_by_id("p1", space_id="alpha")
    record("A5 越权改/删被拒后数据完好", still_there is not None)

    # 属主可正常删除
    ok_del = await database.delete_paper("p1", space_id="alpha")
    record("A6 alpha 属主可删除自身数据", ok_del is True)


async def test_concurrency() -> None:
    """≥20 路并行写入（不同/相同空间混合），断言零 database is locked。"""
    N = 24
    spaces = ["alpha" if i % 2 == 0 else "beta" for i in range(N)]

    async def write_one(i: int, sp: str):
        return await database.insert_paper(make_paper(1000 + i, sp), space_id=sp)

    try:
        results = await asyncio.gather(
            *(write_one(i, sp) for i, sp in enumerate(spaces))
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        locked = "database is locked" in msg.lower()
        record("C0 并发写入无异常", False,
               f"exception={'database is locked' if locked else msg}")
        return

    ok_count = sum(1 for r in results if r is True)
    record("C1 ≥20 路并发写入全部成功（零 locked）",
           ok_count == N, f"ok={ok_count}/{N}")


async def test_wal() -> None:
    async with database.get_db() as conn:
        cur = await conn.execute("PRAGMA journal_mode")
        mode = (await cur.fetchone())[0]
    record("E0 连接后 journal_mode = wal", str(mode).lower() == "wal", f"mode={mode}")


async def test_connection_not_shared() -> None:
    # 行为证据：并发两次 get_db 得到不同连接对象（无跨协程共享）
    async def open_id():
        async with database.get_db() as conn:
            return id(conn)

    ids = await asyncio.gather(open_id(), open_id())
    distinct = ids[0] != ids[1]
    record("F1 并发 get_db 返回不同连接对象", distinct, f"ids={ids}")

    # 代码证据：模块不应持有全局/单例连接属性
    no_global = not any(hasattr(database, a) for a in ("conn", "_conn", "connection", "_connection"))
    record("F2 无模块级全局连接属性", no_global)


async def test_structural_space_columns() -> None:
    await database.init_db()  # 幂等
    async with database.get_db() as conn:
        all_ok = True
        missing = []
        for tbl in database.SPACE_TABLES:
            cols = await (await conn.execute(f"PRAGMA table_info({tbl})")).fetchall()
            col_names = {r["name"] for r in cols}
            has_col = "space_id" in col_names
            # 索引存在性
            cur_idx = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name=? AND name=?",
                (tbl, f"idx_{tbl}_space"),
            )
            idxs = await cur_idx.fetchall()
            has_idx = len(idxs) > 0
            if not (has_col and has_idx):
                all_ok = False
                missing.append(f"{tbl}(col={has_col},idx={has_idx})")
    record(f"H0 SPACE_TABLES 全部含 space_id 列+索引（实际 {len(database.SPACE_TABLES)} 张）",
           all_ok, ("缺失: " + ", ".join(missing)) if missing else "全部到位")


async def test_backward_compat() -> None:
    # 在独立 legacy 目录模拟「老库」：papers 表无 space_id 列
    legacy_dir = TMP / "legacy"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_db = legacy_dir / "ai_research_os.db"

    # 保存当前模块级路径，测试后还原
    saved_data = database.DATA_DIR
    saved_db = database.DB_PATH
    database.DATA_DIR = legacy_dir
    database.DB_PATH = legacy_db

    try:
        # 1) 构造老式 papers 表（含 paper_to_dict 所需全部列，但无 space_id）
        legacy_cols = (
            "id TEXT PRIMARY KEY, title TEXT NOT NULL, authors TEXT NOT NULL, "
            "abstract TEXT NOT NULL, arxiv_id TEXT UNIQUE NOT NULL, pdf_url TEXT NOT NULL, "
            "categories TEXT, published_date TEXT NOT NULL, local_path TEXT, summary TEXT, "
            "tags TEXT, is_read INTEGER DEFAULT 0, is_favorite INTEGER DEFAULT 0, "
            "added_at INTEGER NOT NULL, updated_at INTEGER NOT NULL"
        )
        async with aiosqlite.connect(str(legacy_db)) as c:
            await c.execute(f"CREATE TABLE papers ({legacy_cols})")
            await c.execute(
                "INSERT INTO papers (id, title, authors, abstract, arxiv_id, pdf_url, "
                "published_date, added_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                ("legacy1", "Old Paper", "[]", "old abstract", "oldarXiv.v1",
                 "http://x/old.pdf", "2020-01-01", 1, 1),
            )
            await c.commit()

        # 2) 运行幂等迁移 init_db
        await database.init_db()

        # 3) 存量行应被打上 __default__
        async with database.get_db() as conn:
            cur = await conn.execute("SELECT space_id FROM papers WHERE id='legacy1'")
            row = await cur.fetchone()
        got_space = (row is not None and row["space_id"] == database.DEFAULT_SPACE)
        record("D1 存量无 space_id 数据归 __default__", got_space,
               f"space_id={row['space_id'] if row else None}")

        # 4) 存量数据在默认空间可访问，跨空间不可见
        visible_default = await database.get_all_papers(space_id=database.DEFAULT_SPACE)
        in_default = any(p["id"] == "legacy1" for p in visible_default)
        hidden_other = not any(p["id"] == "legacy1"
                               for p in await database.get_all_papers(space_id="other"))
        record("D2 存量数据在 __default__ 可访问", in_default)
        record("D3 存量数据对其它空间不可见", hidden_other)

        # 5) cron JSON 仅迁移一次
        cron_json = legacy_dir / "cron_jobs.json"
        cron_json.write_text(
            '{"jobs":['
            '{"id":"c1","name":"j1","schedule":"* * * * *","command":"echo 1"},'
            '{"id":"c2","name":"j2","schedule":"* * * * *","command":"echo 2"}'
            ']}', encoding="utf-8",
        )
        await database.init_db()  # 第一次：应导入 2 条
        async with database.get_db() as conn:
            n1 = (await (await conn.execute("SELECT COUNT(*) FROM cron_jobs")).fetchone())[0]
        await database.init_db()  # 第二次：应跳过（不重复导入）
        async with database.get_db() as conn:
            n2 = (await (await conn.execute("SELECT COUNT(*) FROM cron_jobs")).fetchone())[0]
        record("D4 cron JSON 首次迁移生效", n1 == 2, f"count_after_1st={n1}")
        record("D5 cron JSON 二次运行不重复导入", n2 == 2, f"count_after_2nd={n2}")
    finally:
        database.DATA_DIR = saved_data
        database.DB_PATH = saved_db


async def run_async_tests() -> None:
    await test_structural_space_columns()
    await test_isolation()
    await test_concurrency()
    await test_wal()
    await test_connection_not_shared()
    await test_backward_compat()


# ---------------------------------------------------------------------------
# G. 前端 X-Space-Key 注入唯一性（真实文件系统 grep）
# ---------------------------------------------------------------------------
def test_frontend_injection_unique() -> None:
    frontend_src = PROJECT_ROOT / "frontend" / "src"
    if not frontend_src.exists():
        record("G0 前端源码目录存在", False, str(frontend_src))
        return
    record("G0 前端源码目录存在", True)

    files_with_token: list[str] = []
    # 真正“注入请求头”的写法：'X-Space-Key': ... 或 headers['X-Space-Key'] = ...
    assign_re = re.compile(r"""['"]X-Space-Key['"]\s*[:=]""")
    assign_files: list[str] = []

    for p in frontend_src.rglob("*"):
        if p.suffix in (".ts", ".tsx", ".js", ".jsx") and p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "X-Space-Key" in text:
                files_with_token.append(str(p.relative_to(PROJECT_ROOT)))
                # 排除纯注释/字符串说明中出现（仅当存在“赋值/注入”语法才算注入点）
                if assign_re.search(text):
                    assign_files.append(str(p.relative_to(PROJECT_ROOT)))

    print(f"    含 X-Space-Key 的文件: {files_with_token}")
    print(f"    真正注入请求头的文件:   {assign_files}")

    assign_norm = [f.replace("\\", "/") for f in assign_files]
    only_api = assign_norm == ["frontend/src/services/apiMonitor.ts"]
    record("G1 唯一注入点为 apiMonitor.ts", only_api,
           f"assign_files={assign_files}")

    # 其它仅含注释引用的文件（如 SpaceGate.tsx 的文档注释）不视为注入点
    non_inject = [f for f in files_with_token if f not in assign_files]
    if non_inject:
        print(f"    （注：以下文件仅含注释/说明引用，非注入点：{non_inject}）")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 70)
    print("AI-Research-OS space-key 软隔离 — QA 独立验证")
    print(f"隔离测试库: {TMP}")
    print("=" * 70)

    print("\n--- B. HTTP 层 400 / 豁免 ---")
    test_http_400_and_exemption()

    print("\n--- A/C/E/F/H/D. 数据库层（真实 aiosqlite 异步）---")
    asyncio.run(run_async_tests())

    print("\n--- G. 前端注入唯一性 ---")
    test_frontend_injection_unique()

    # 汇总
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = total - passed
    print("\n" + "=" * 70)
    print(f"汇总: 共 {total} 项 | 通过 {passed} | 失败 {failed}")
    if failed:
        print("失败项:")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  - {name}  ({detail})")
    print("=" * 70)

    # 清理临时库
    try:
        shutil.rmtree(TMP, ignore_errors=True)
    except Exception:
        pass

    verdict = "ALL_PASS" if failed == 0 else "HAS_FAILURES"
    print(f"VERDICT: {verdict}")
    return None


if __name__ == "__main__":
    main()
