# -*- coding: utf-8 -*-
"""QA 验证：POST /api/papers/fetch 契约兼容性（修复 422 回归）。

背景：后端端点原本只接受 JSON body（FetchPapersRequest），而前端
papersApi.ts / aiAgent.ts 用 query 参数（max / keywords）且不带 body，
FastAPI 解析必填 body 失败 → 422 Unprocessable Entity。

修复后端点同时兼容 query 参数与 body。本脚本用 FastAPI TestClient
验证（monkeypatch 掉 arXiv 网络请求与 DB 写入，纯契约测试）：
  1. 仅 query 参数（前端现状契约，原 bug 场景）→ 200
  2. 仅 JSON body（schema 契约）→ 200
  3. query + body 同时给出 → query 优先
  4. keywords query 逗号分隔 → 拆分为多关键词
  5. keywords query 单值（含空格短语）→ 整体作为一个关键词
  6. 入库调用携带 space_id（空间隔离不回归）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.server import db
from backend.server.routers.papers import router as papers_router

# ---- monkeypatch：不触网、不写库 ------------------------------------------

captured: dict = {}


def fake_fetch_papers(search_query: str = "cat:cs.CV", keywords: list = None, **kwargs) -> list:
    captured["search_query"] = search_query
    captured["keywords"] = keywords
    captured["max_results"] = kwargs.get("max_results")
    return [{"arxivId": "2401.00001", "title": "stub paper"}]


async def fake_insert_paper(paper, space_id=None, **kwargs) -> bool:
    captured["insert_space_id"] = space_id
    return True


import scripts.fetch_arxiv as fetch_arxiv_mod

fetch_arxiv_mod.fetch_papers = fake_fetch_papers
db.database.insert_paper = fake_insert_paper

app = FastAPI()
app.include_router(papers_router)
client = TestClient(app)
HEADERS = {"X-Space-Key": "qa-test-space"}

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


# 1. 仅 query 参数（原 bug 场景：POST /api/papers/fetch?max=10&keywords=image+generation）
captured.clear()
resp = client.post("/api/papers/fetch?max=10&keywords=image+generation", headers=HEADERS)
body = resp.json() if resp.status_code == 200 else {}
check(
    "query-only 调用返回 200（原 422 场景）",
    resp.status_code == 200,
    f"status={resp.status_code}",
)
check(
    "query-only: keywords 传短语",
    captured.get("keywords") == ["image generation"],
    f"keywords={captured.get('keywords')}",
)
check(
    "query-only: max=10 生效",
    captured.get("max_results") == 10,
    f"max_results={captured.get('max_results')}",
)
check(
    "query-only: 响应含 papers/total/inserted",
    bool(body.get("papers")) and body.get("total") == 1 and body.get("inserted") == 1,
    f"keys={sorted(body.keys())}",
)

# 2. 仅 JSON body（schema 契约）
captured.clear()
resp = client.post(
    "/api/papers/fetch",
    headers={**HEADERS, "Content-Type": "application/json"},
    json={"query": "cat:cs.CL", "keywords": ["llm", "agent"], "max_results": 5},
)
check("body-only 调用返回 200", resp.status_code == 200, f"status={resp.status_code}")
check(
    "body-only: keywords 列表透传",
    captured.get("keywords") == ["llm", "agent"],
    f"keywords={captured.get('keywords')}",
)
check(
    "body-only: max_results=5 生效",
    captured.get("max_results") == 5,
    f"max_results={captured.get('max_results')}",
)
check(
    "body-only: query 覆盖默认分类",
    captured.get("search_query") == "cat:cs.CL",
    f"search_query={captured.get('search_query')}",
)

# 3. query + body 同时给出 → query 优先
captured.clear()
resp = client.post(
    "/api/papers/fetch?max=3&keywords=a%2Cb",
    headers={**HEADERS, "Content-Type": "application/json"},
    json={"keywords": ["x"], "max_results": 20},
)
check("query+body 调用返回 200", resp.status_code == 200, f"status={resp.status_code}")
check(
    "query+body: query 参数优先（max=3）",
    captured.get("max_results") == 3,
    f"max_results={captured.get('max_results')}",
)
check(
    "query+body: keywords query 逗号拆分",
    captured.get("keywords") == ["a", "b"],
    f"keywords={captured.get('keywords')}",
)

# 4. 无任何参数 → 默认值不 422
captured.clear()
resp = client.post("/api/papers/fetch", headers=HEADERS)
check(
    "无参数调用返回 200（默认 max_results=10）",
    resp.status_code == 200 and captured.get("max_results") == 10,
    f"status={resp.status_code}, max_results={captured.get('max_results')}",
)
check(
    "无参数: 默认分类 cat:cs.CV",
    captured.get("search_query") == "cat:cs.CV",
    f"search_query={captured.get('search_query')}",
)

# 5. 空间隔离：insert_paper 拿到 X-Space-Key 归一后的 space_id
check(
    "insert_paper 携带 space_id（空间隔离）",
    captured.get("insert_space_id") == "qa-test-space",
    f"space_id={captured.get('insert_space_id')}",
)

# 6. 缺 X-Space-Key 仍应 400（隔离语义不回归）
resp = client.post("/api/papers/fetch?max=5")
check("缺 X-Space-Key 返回 400", resp.status_code == 400, f"status={resp.status_code}")

# ---- 汇总 -----------------------------------------------------------------

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
print()
print(f"TOTAL: {len(results)}  PASS: {len(results) - len(failed)}  FAIL: {len(failed)}")
sys.exit(1 if failed else 0)
