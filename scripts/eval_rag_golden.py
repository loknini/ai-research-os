#!/usr/bin/env python3
"""RAG golden 评测基线（P0 门禁）：确定性合成 + 落盘复用 + LLM judge（可选）。

用法：
    python -m scripts.eval_rag_golden build [space]   # 生成 data/eval/golden_rag.json（默认 50 条）
    python -m scripts.eval_rag_golden run [space]     # 跑评测，写 data/eval/report_rag_golden.json
    python -m scripts.eval_rag_golden gate [space]    # 同 run，并按固定阈值返回非零退出码

指标：
    * hit@1 / hit@5：gold_keys 任一命中即算（大小写不敏感，纯检索，无需 LLM）
    * faithfulness：仅 LLM 已配置时，用 llm_client 判“答案是否只基于命中片段”（0/1）；
      未配置记 n/a，检索指标照常输出。
合成确定性（seed 42）：同一库多次 build 结果一致；库内容变了请人工 review  diff 后再跑。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import random
import re
import sys
import time

PROJECT = pathlib.Path(__file__).resolve().parent.parent

if __package__ in (None, ""):
    print("请从项目根目录运行：python -m scripts.eval_rag_golden <build|run|gate> [space]", file=sys.stderr)
    raise SystemExit(2)

from scripts import database as db

GOLDEN_PATH = PROJECT / "data" / "eval" / "golden_rag.json"
REPORT_PATH = PROJECT / "data" / "eval" / "report_rag_golden.json"
TARGET_N = 50
GATE_HIT1 = 0.75
GATE_HIT5 = 0.90
GATE_FAITH = 0.70

_Q_TEMPLATES = [
    "论文《{t}》的核心方法是什么？",
    "论文《{t}》的主要结论是什么？",
    "请介绍一下《{t}》这篇论文。",
    "笔记《{t}》讲了什么？",
    "关于“{t}”，资料里是怎么说的？",
]


def _keys(text: str, limit: int = 3) -> list:
    """抽 gold keys：长度≥2 的英文词/中文词优先，回退前 8 字符。"""
    toks = re.findall(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fff]{2,}", text or "")
    seen: list = []
    for t in toks:
        if t.lower() not in [s.lower() for s in seen]:
            seen.append(t)
        if len(seen) >= limit:
            break
    if not seen and text:
        seen = [text.strip()[:8]]
    return seen


async def build(space: str = "__default__", n: int = TARGET_N) -> list:
    from backend.server.rag import service as rag  # noqa: F401  # 确保管线可 import

    await db.init_db()
    papers = await db.get_all_papers(space_id=space, limit=50)
    try:
        notes = await db.get_all_notes(space_id=space, limit=50)
    except Exception:
        notes = []
    pool: list = []
    for p in papers:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        keys = _keys(title) + _keys(p.get("abstract") or "", 2)
        for qi in range(min(3, len(_Q_TEMPLATES))):
            pool.append({
                "id": f"paper-{p.get('arxivId') or p.get('id')}-{qi}",
                "question": _Q_TEMPLATES[qi].format(t=title[:60]),
                "gold_keys": keys,
                "kind": "paper",
            })
    for n_ in notes:
        title = (n_.get("title") or "").strip() or "未命名笔记"
        keys = _keys(title) + _keys(n_.get("content") or "", 2)
        for qi in (3, 4):
            pool.append({
                "id": f"note-{n_.get('id')}-{qi}",
                "question": _Q_TEMPLATES[qi].format(t=title[:60]),
                "gold_keys": keys,
                "kind": "note",
            })
    random.seed(42)
    random.shuffle(pool)
    golden = pool[:n]
    # 库太小补足（标记 synthetic，权重低）
    i = 0
    while len(golden) < n and pool:
        base = pool[i % len(pool)]
        golden.append({**base, "id": f"{base['id']}-x{i}", "synthetic": True})
        i += 1
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(json.dumps(golden, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"golden built: {len(golden)} -> {GOLDEN_PATH}")
    return golden


def _judge(question: str, answer: str, ctx: str) -> int | None:
    """LLM 判 faithfulness：答案是否只基于给定片段（1/0）；LLM 不可用回 None。"""
    from backend.server.llm import llm_client

    if not llm_client.configured:
        return None
    prompt = ("判断下面「回答」是否完全基于「文档片段」得出（无编造、无超出片段的信息）。\n"
              f"问题：{question}\n片段：{ctx[:2000]}\n回答：{answer[:2000]}\n"
              "只回复 1（是）或 0（否）。")
    try:
        out = (llm_client.call_llm([{"role": "user", "content": prompt}]) or "").strip()
    except Exception:
        return None
    m = re.search(r"[01]", out)
    return int(m.group(0)) if m else None


async def run(space: str = "__default__", max_items: int = 0) -> dict:
    """跑评测（可断点续跑：已完成的 id 自动跳过；max_items>0 则本轮最多做 N 条）。

    单条约 20s（60k 切片全量扫描 + LLM 作答），50 条约 18 分钟，请分片跑：
    run dream 8 → run dream 8 → … 直到 done == 50。每条落盘一次，被杀不丢。
    """
    report = await _run_slice(space, max_items)
    print(json.dumps({k: v for k, v in report.items() if k != "details"},
                     ensure_ascii=False, indent=2))
    return report


async def _run_slice(space: str, max_items: int) -> dict:
    from backend.server.rag import service as rag

    await db.init_db()
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    done: dict = {}
    if REPORT_PATH.exists():
        try:
            prev = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
            for r in prev.get("details", []):
                done[r.get("id")] = r
        except Exception:
            pass
    todo = [g for g in golden if g.get("id") not in done]
    if max_items > 0:
        todo = todo[:max_items]
    for g in todo:
        t0 = time.time()
        try:
            res = await rag.query(space, g["question"], top_k=5)
        except Exception as exc:  # noqa: BLE001 - 单条失败记 0，不中断整轮
            done[g["id"]] = {"id": g["id"], "error": str(exc)[:120],
                             "hit1": False, "hit5": False, "faith": None}
            _flush(done)
            continue
        texts = [(h.get("content") or "").lower() for h in res.get("hits", [])]
        keys = [k.lower() for k in g.get("gold_keys", []) if k]
        hit = lambda ts: any(k in t for k in keys for t in ts) if keys else False  # noqa: E731
        faith = _judge(g["question"], res.get("answer", ""),
                       "\n".join(texts)) if hit(texts) else None
        done[g["id"]] = {"id": g["id"], "kind": g.get("kind"),
                         "hit1": hit(texts[:1]), "hit5": hit(texts), "faith": faith,
                         "mode": res.get("mode"), "ms": int((time.time() - t0) * 1000)}
        _flush(done)
    return _summarize(done)


def _flush(done: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(_summarize(done), ensure_ascii=False, indent=2),
                           encoding="utf-8")


def _summarize(done: dict) -> dict:
    results = list(done.values())
    golden_n = len(json.loads(GOLDEN_PATH.read_text(encoding="utf-8")))
    n = len(results)
    hit1 = sum(1 for r in results if r.get("hit1")) / n if n else 0.0
    hit5 = sum(1 for r in results if r.get("hit5")) / n if n else 0.0
    frows = [r["faith"] for r in results if r.get("faith") is not None]
    faith = sum(frows) / len(frows) if frows else None
    modes: dict = {}
    for r in results:
        modes[r.get("mode")] = modes.get(r.get("mode"), 0) + 1
    return {"n": golden_n, "done": n, "hit@1": round(hit1, 4), "hit@5": round(hit5, 4),
            "faithfulness": round(faith, 4) if faith is not None else None,
            "modes": modes, "details": results}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="构建、运行或门禁 RAG 黄金集评测")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="从当前空间生成黄金集")
    build_parser.add_argument("space", nargs="?", default="__default__")
    build_parser.add_argument("--count", type=int, default=TARGET_N)

    for command, help_text in (
        ("run", "运行评测并写入报告"),
        ("gate", "运行评测并检查固定阈值"),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("space", nargs="?", default="__default__")
        command_parser.add_argument("max_items", nargs="?", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "build":
        if args.count < 1:
            _build_parser().error("--count 必须大于 0")
        asyncio.run(build(args.space, args.count))
        return 0

    report = asyncio.run(run(args.space, args.max_items))
    if args.command != "gate":
        return 0

    failures = []
    if report.get("done") != report.get("n"):
        failures.append(f"incomplete {report.get('done')}/{report.get('n')}")
    if float(report.get("hit@1") or 0) < GATE_HIT1:
        failures.append(f"hit@1 < {GATE_HIT1}")
    if float(report.get("hit@5") or 0) < GATE_HIT5:
        failures.append(f"hit@5 < {GATE_HIT5}")
    faith = report.get("faithfulness")
    if faith is not None and float(faith) < GATE_FAITH:
        failures.append(f"faithfulness < {GATE_FAITH}")
    if failures:
        print("RAG_GOLDEN_GATE_FAILED: " + "; ".join(failures))
        return 1
    print("RAG_GOLDEN_GATE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
