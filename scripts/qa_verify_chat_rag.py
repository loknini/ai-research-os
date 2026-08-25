"""验证 Chat Hub 的 RAG 接地接入（隔离 DATA_DIR + TestClient 真实流式端点）。

覆盖：
  * 开启 rag_enabled 时，后端会检索已索引文档并回传 rag_sources 事件（含命中片段）。
  * 关闭 rag_enabled 时，rag_sources.enabled=False 且 sources 为空。
不依赖 LLM（检索走关键词降级；流式生成阶段 LLM 不可用时仅报错事件，不影响断言）。
"""
import asyncio
import json
import os
import sys
import tempfile

# 把项目根目录加到 sys.path（脚本在 scripts/ 下，需能 import ``scripts`` 与 ``backend`` 包）。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="qa_chat_rag_")
os.environ["DATA_DIR"] = TMP
os.environ["DEFAULT_SPACE"] = "__default__"

import scripts.database as database  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from backend.server.main import app  # noqa: E402

SPACE = "__default__"


async def seed() -> None:
    await database.init_db()
    source_id = "src-chat"
    ok = await database.create_rag_source(
        source_id, SPACE, "测试源", ["/tmp/x"], True, ["pdf", "txt", "md"],
        embedding_model="", status="ready")
    assert ok, "create_rag_source failed"
    doc_id = "doc-chat"
    await database.create_rag_document(
        doc_id, SPACE, source_id, "/tmp/paper.txt", "paper.txt", "txt", 100, 1, 200, 0)
    chunks = [
        {
            "id": "c1", "source_id": source_id, "doc_id": doc_id, "chunk_index": 0,
            "content": "梯度下降是优化神经网络参数的核心方法。", "page_start": 1, "page_end": 1,
            "char_start": 0, "char_end": 20, "embedding": None, "token_count": 8,
        },
        {
            "id": "c2", "source_id": source_id, "doc_id": doc_id, "chunk_index": 1,
            "content": "反向传播用于高效计算梯度。", "page_start": 2, "page_end": 2,
            "char_start": 20, "char_end": 40, "embedding": None, "token_count": 8,
        },
    ]
    await database.insert_rag_chunks(chunks, SPACE)
    await database.update_rag_document(doc_id, SPACE, chunk_count=2)
    await database.update_rag_source(
        source_id, SPACE, status="ready", doc_count=1, chunk_count=2,
        embed_mode="keyword", embedding_model="")
    print("seed OK")


def collect_sse(client: TestClient, payload: dict) -> list:
    events = []
    with client.stream(
        "POST", "/api/chat/completions/stream", json=payload,
        headers={"X-Space-Key": SPACE},
    ) as r:
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                continue
            try:
                events.append(json.loads(data))
            except Exception:
                pass
    return events


def main() -> None:
    asyncio.run(seed())
    client = TestClient(app)

    # 1) 开启 RAG，query 命中关键词「梯度下降」
    events = collect_sse(client, {
        "messages": [{"role": "user", "content": "梯度下降是什么？"}],
        "rag_enabled": True,
    })
    rag_evt = next((e for e in events if e.get("type") == "rag_sources"), None)
    assert rag_evt is not None, "未收到 rag_sources 事件"
    assert rag_evt["enabled"] is True, "enabled 应为 True"
    assert len(rag_evt["sources"]) > 0, "开启 RAG 却无来源"
    assert any("梯度下降" in s["snippet"] for s in rag_evt["sources"]), "未命中相关片段"
    print("PASS 开启RAG -> rag_sources 含命中片段:", rag_evt["sources"][0]["fileName"],
          "| mode:", rag_evt["mode"])

    # 2) 关闭 RAG -> enabled False 且 sources 空
    events2 = collect_sse(client, {
        "messages": [{"role": "user", "content": "梯度下降是什么？"}],
        "rag_enabled": False,
    })
    rag2 = next((e for e in events2 if e.get("type") == "rag_sources"), None)
    assert rag2 is not None and rag2["enabled"] is False, "关闭时 enabled 应为 False"
    assert len(rag2["sources"]) == 0, "关闭时 sources 应为空"
    print("PASS 关闭RAG -> enabled=False, sources=[]")

    print("ALL_CHAT_RAG_PASS")


if __name__ == "__main__":
    main()
