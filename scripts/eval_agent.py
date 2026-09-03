#!/usr/bin/env python3
"""Agent 10题小跑：自动合成 + agnes-2.5-flash Judge"""
import asyncio, json, random, pathlib, time
from scripts import database as db
from backend.server import agent_runner, db as sdb

TASKS = [
    "为论文中心加标签批量导出",
    "为任务清单加优先级筛选",
    "写一个待办 CLI 的 README",
    "把笔记搜索改成分词匹配",
    "给实验对比加图表",
    "为软件项目加部署状态看板",
    "给公式识别加历史收藏",
    "为引用生成加 BibTeX 校验",
    "给 Chat 加上下文压缩提示",
    "为 Cron 加下一次执行预估",
]

async def main(limit=10):
    await db.init_db()
    sample = TASKS[:limit]
    results = []
    for req in sample:
        run_id = await agent_runner.submit_run("__default__", req, None, None)
        # 轮询至多 60s
        for _ in range(60):
            await asyncio.sleep(1)
            run = await sdb.database.get_agent_run(run_id, "__default__")
            if run and run["status"] in ("completed", "failed", "cancelled"):
                break
        run = await sdb.database.get_agent_run(run_id, "__default__")
        ok = run and run["status"] == "completed"
        results.append({"requirement": req, "status": run["status"] if run else "unknown", "success": ok})
    succ = sum(r["success"] for r in results) / len(results) if results else 0
    out = {"model": "agnes-2.5-flash", "success_rate": succ, "details": results}
    path = pathlib.Path("data/eval/report_agent.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    import sys
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10))
