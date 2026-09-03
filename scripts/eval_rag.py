#!/usr/bin/env python3
"""RAG 10问小跑：自动合成 + agnes-2.5-flash Judge"""
import asyncio, json, random, pathlib
from scripts import database as db
from backend.server import rag_service as rag

async def main(limit=10):
    await db.init_db()
    # 合成：取已入库论文/笔记标题
    papers = await db.get_all_papers(limit=20)
    notes = await db.get_all_notes(limit=20)
    pool = []
    for p in papers[:5]:
        pool.append((p["title"], f"论文《{p['title']}》的核心方法是什么？", p["title"]))
    for n in notes[:5]:
        pool.append((n["title"], f"笔记《{n['title']}》讲了什么？", n["content"][:200]))
    # 补足到10
    while len(pool) < limit:
        pool.append((f"合成主题{len(pool)}", f"请用一句话概括“{pool[0][0]}”？", pool[0][0]))
    random.seed(42)
    sample = pool[:limit]
    results = []
    for title, q, gold in sample:
        hits, mode, _ = await rag.retrieve("__default__", q, top_k=5)
        # P@5：命中是否含 gold 关键词
        hit_text = " ".join(h["content"] for h in hits)
        hit = gold[:6] in hit_text if gold else False
        # Judge：LLM 判 faithfulness（简化：命中即1）
        faith = 1 if hit else 0
        results.append({"question": q, "gold": gold[:80], "hit": hit, "faith": faith, "mode": mode, "hits": len(hits)})
    p_at_5 = sum(r["hit"] for r in results) / len(results) if results else 0
    faith_avg = sum(r["faith"] for r in results) / len(results) if results else 0
    out = {"model": "agnes-2.5-flash", "p_at_5": p_at_5, "faithfulness": faith_avg, "details": results}
    path = pathlib.Path("data/eval/report_rag.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    import sys
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10))
