#!/usr/bin/env python3
"""RAG 子系统独立验证脚本（隔离 DATA_DIR，打桩 LLM/嵌入）。

覆盖：
  * 文件发现（多路径 / 递归 / 类型过滤）
  * 索引编排（向量模式 + 关键词降级）
  * 切片落库与向量写入
  * 检索 + 带引用回答（向量 / 关键词双路）
  * 源 CRUD 与级联删除
运行：python scripts/qa_verify_rag.py
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

TMP = Path(tempfile.mkdtemp(prefix="rag_qa_"))

import scripts.database as database  # noqa: E402

# 隔离数据库到临时目录（覆盖模块级全局）。
database.DATA_DIR = TMP
database.DB_PATH = TMP / "qa_rag.db"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from backend.server import rag_service  # noqa: E402
from backend.server.llm import llm_client  # noqa: E402

# 让 llm_client 视为「已配置」，并打桩嵌入 / 对话。
llm_client.settings.llm_api_key = "test"
llm_client.settings.llm_base_url = "http://localhost/v1"
llm_client.settings.llm_model = "test-model"


def fake_embed(texts, model=None):
    return [[float(len(t)), float(t.count("a")), float(t.count("e")), float(len(set(t)))]
            for t in texts]


def fake_call_llm(messages, **kw):
    return "测试回答，引用见 [1]。"


llm_client.embed = fake_embed
llm_client.call_llm = fake_call_llm

SPACE = "qa_space"


def make_corpus() -> Path:
    corpus = TMP / "corpus"
    (corpus / "sub").mkdir(parents=True, exist_ok=True)
    (corpus / "a.txt").write_text(
        "人工智能是计算机科学的一个分支。深度学习推动了自然语言处理的进步。", encoding="utf-8")
    (corpus / "sub" / "b.md").write_text(
        "# 标题\n\nRAG 检索增强生成结合了检索与生成模型。向量数据库用于存储嵌入。", encoding="utf-8")
    (corpus / "ignore.log").write_text("should be ignored", encoding="utf-8")
    return corpus


async def main() -> None:
    await database.init_db()
    corpus = make_corpus()

    # 1) 文件发现：递归 + 默认类型过滤应排除 .log
    files = rag_service.discover_files([str(corpus)], True, None)
    names = sorted(f.name for f in files)
    assert "a.txt" in names and "b.md" in names and "ignore.log" not in names, f"discover 失败: {names}"
    print("PASS discover_files:", names)

    # 2) 索引（向量模式）—— 仿照路由：先建源，再索引
    await database.create_rag_source("src-vec", SPACE, "src-vec", [str(corpus)], True,
                                     ["pdf", "txt", "md"], embedding_model="fake", status="indexing")
    res = await rag_service.index_source("src-vec", SPACE, [str(corpus)], True, None,
                                         embedding_model="fake")
    assert res["status"] == "ready", res
    assert res["doc_count"] == 2, res
    assert res["chunk_count"] > 0, res
    assert res["embed_mode"] == "vector", res
    print("PASS index_source(向量):", res)

    chunks = await database.get_rag_chunks_for_retrieval(SPACE)
    assert len(chunks) == res["chunk_count"]
    assert all(c["embedding"] for c in chunks), "存在缺失向量的切片"
    print("PASS 切片均含向量, 总数 =", len(chunks))

    # 3) 检索 + 回答（向量）
    r = await rag_service.query(SPACE, "什么是 RAG 检索增强生成？", top_k=3)
    assert r["mode"] == "vector", r["mode"]
    assert len(r["hits"]) > 0, r
    assert len(r["sources"]) > 0
    assert "[1]" in r["answer"], r["answer"]
    print("PASS query(向量):", {k: r[k] for k in ("mode", "topK", "embedAvailable")},
          "hits =", len(r["hits"]))

    # 4) 关键词降级：破坏嵌入后重新索引
    llm_client.embed = lambda texts, model=None: None
    await database.create_rag_source("src-kw", SPACE, "src-kw", [str(corpus)], True,
                                     ["pdf", "txt", "md"], status="indexing")
    res2 = await rag_service.index_source("src-kw", SPACE, [str(corpus)], True, None,
                                          embedding_model="fake")
    assert res2["embed_mode"] == "keyword", res2
    r2 = await rag_service.query(SPACE, "深度学习", top_k=3)
    assert r2["mode"] == "keyword", r2["mode"]
    assert len(r2["hits"]) > 0
    print("PASS query(关键词降级):", r2["mode"], "hits =", len(r2["hits"]))

    # 5) 源列表 / 统计
    srcs = await database.get_rag_sources(SPACE)
    assert len(srcs) == 2, srcs
    stats = await database.get_rag_stats(SPACE)
    assert stats["sourceCount"] == 2
    print("PASS 源列表/统计:", stats)

    # 6) 级联删除
    ok = await database.delete_rag_source("src-vec", SPACE)
    assert ok
    after = await database.get_rag_chunks_for_retrieval(SPACE)
    assert all(c["sourceId"] != "src-vec" for c in after)
    print("PASS 级联删除")

    print("\nALL_RAG_QA_PASS")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
