#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台非阻塞 Agent runner 验证脚本（隔离 DATA_DIR，真实 aiosqlite + TestClient）。

覆盖：
  A. 非阻塞提交：submit_run 立即返回 run_id，初始 status=running；后台线程推进至 completed，
     事件落库（agent_run_events），run_complete 事件存在，summary 含角色键。
  B. 空间隔离：不同 space 的 run 互不可见（get_agent_run 传错 space 返回 None）。
  C. 取消：提交慢速 run 后 cancel_run，最终 status=cancelled。
  D. HTTP 冒烟：TestClient 打真实路由 POST /api/agent/runs + GET /api/agent/runs/{id}，
     验证 sys.path 修复后 `import agent_service` 端到端可用（修复前会在 import 阶段崩）。
"""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# 隔离数据目录（必须在 import backend.server 之前设置 DATA_DIR）
_TMP = tempfile.mkdtemp(prefix="qa_agent_runner_")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("LLM_BASE_URL", "http://127.0.0.1:9/none")  # 不应被用到（已打桩）

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import backend.server as _bs  # noqa: F401  确保 backend 包已导入（不再依赖 sys.path 注入）
from backend.server import agent_service  # backend/server/agent_service.py（正规包导入）
from scripts import database as db  # scripts/database.py（与后端同一模块对象）
import backend.server.agent_runner as agent_runner
from backend.server.agent_runner import submit_run, cancel_run  # noqa: F401

PASS = 0
FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {msg}")
    else:
        FAIL += 1
        print(f"  [FAIL] {msg}")


# ---- 打桩 LLM（确定性强，避免真实联网）----
_SPEED = 0.05  # 普通 run 每角色耗时


def _fake_call(messages, temperature=0.7):
    time.sleep(_SPEED)
    agent = messages[-1]["content"][:20]
    return json.dumps({"success": True, "raw_output": f"fake-output::{agent}"})


def _install_stub(speed=0.05):
    agent_service.call_llm = lambda m, temperature=0.7: _fake_call_sleep(m, temperature, speed)
    agent_service.PARSERS = {"design": lambda t: None, "plan": lambda t: None}


def _fake_call_sleep(messages, temperature, speed):
    time.sleep(speed)
    return json.dumps({"success": True, "raw_output": f"fake::{messages[-1]['content'][:12]}"})


async def _wait_terminal(run_id, space, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = await db.get_agent_run_status(run_id, space)
        if st in ("completed", "failed", "cancelled"):
            return st
        await asyncio.sleep(0.05)
    return await db.get_agent_run_status(run_id, space)


async def test_nonblocking():
    print("\n[A] 非阻塞提交 + 完成")
    _install_stub(0.05)
    rid = await submit_run("qa", "做一个待办事项小工具", project_id="p1", roles=["architect", "planner"])
    check(isinstance(rid, str) and len(rid) > 8, f"submit_run 立即返回 run_id ({rid[:8]}…)")
    st0 = await db.get_agent_run_status(rid, "qa")
    check(st0 == "running", f"提交瞬间 status=running（非阻塞）而非 completed（实际 {st0}）")

    # 断言：提交返回时后台线程确实还在跑（即没在请求里同步等完）
    thr = agent_runner._RUN_THREADS.get(rid)
    check(thr is not None and thr.is_alive(), "提交后后台线程仍在运行（证明未阻塞请求）")

    final = await _wait_terminal(rid, "qa")
    check(final == "completed", f"后台推进至 completed（实际 {final}）")

    events = await db.get_agent_run_events(rid, "qa")
    check(len(events) > 0, f"事件已落库（{len(events)} 条）")
    types = {e["type"] for e in events}
    check("run_complete" in types, "存在 run_complete 事件")
    check("run_start" in types, "存在 run_start 事件")

    meta = await db.get_agent_run(rid, "qa")
    check(meta.get("status") == "completed", "get_agent_run 状态一致")
    summ = meta.get("resultSummary") or {}
    check("architect" in summ and "planner" in summ, f"resultSummary 含角色键（{list(summ.keys())}）")


async def test_space_scoping():
    print("\n[B] 空间隔离")
    _install_stub(0.05)
    rid = await submit_run("SPACE_B", "另一个需求", roles=["architect"])
    # 用错 space 查不到
    none_meta = await db.get_agent_run(rid, "WRONG_SPACE")
    check(none_meta is None, "错 space 查询返回 None（隔离生效）")
    # 列表不包含其它 space
    lst = await db.list_agent_runs(space_id="qa")
    ids = {r["id"] for r in lst}
    check(rid not in ids, "list_agent_runs(space=qa) 不含 SPACE_B 的 run")
    await _wait_terminal(rid, "SPACE_B")


async def test_cancel():
    print("\n[C] 取消")
    _install_stub(0.3)  # 每角色 0.3s，留出取消窗口
    rid = await submit_run("qa", "长任务", roles=["architect", "planner"])
    await asyncio.sleep(0.02)
    ok = await cancel_run(rid, "qa")
    check(ok is True, "cancel_run 返回 True")
    final = await _wait_terminal(rid, "qa", timeout=10)
    check(final == "cancelled", f"最终 status=cancelled（实际 {final}）")
    events = await db.get_agent_run_events(rid, "qa")
    check(any(e["type"] == "run_cancelled" for e in events), "存在 run_cancelled 事件")


def test_http_smoke():
    print("\n[D] HTTP 冒烟（TestClient，验证路由 import 修复）")
    try:
        from fastapi.testclient import TestClient
        from backend.server.main import app
    except Exception as exc:  # noqa: BLE001
        check(False, f"导入 FastAPI app 失败（sys.path 未修复？）：{exc}")
        return

    _install_stub(0.05)

    # DB 已在 main() 开头 init_db()（同一 DATA_DIR），此处直接复用。
    # space-key 隔离要求 X-Space-Key 头；冒烟用固定 key，POST 与 GET 保持一致。
    H = {"X-Space-Key": "qasmoke"}
    with TestClient(app) as client:
        resp = client.post("/api/agent/runs", json={"requirement": "HTTP 冒烟需求", "roles": ["architect"]}, headers=H)
        check(resp.status_code == 200, f"POST /api/agent/runs -> 200（实际 {resp.status_code}）")
        body = resp.json()
        rid = body.get("runId")
        check(bool(rid), f"返回 runId={rid}")

        if rid:
            # 轮询 GET /api/agent/runs/{id} 直到完成（注意返回结构是 {run, events, done}）
            final = None
            for _ in range(200):
                r2 = client.get(f"/api/agent/runs/{rid}", headers=H)
                if r2.status_code == 200:
                    final = r2.json().get("run", {}).get("status")
                    if final in ("completed", "failed", "cancelled"):
                        break
                time.sleep(0.05)
            check(final == "completed", f"GET /runs/{{id}} 最终 completed（实际 {final}）")
            r2 = client.get(f"/api/agent/runs/{rid}", headers=H)
            j = r2.json()
            run = j.get("run", {})
            check(len(j.get("events", [])) > 0, f"GET /runs/{{id}} 返回事件（{len(j.get('events', []))} 条）")
            check(run.get("spaceId") == "qasmoke", f"spaceId 与请求头一致（实际 {run.get('spaceId')}）")


async def main():
    await db.init_db()
    await test_nonblocking()
    await test_space_scoping()
    await test_cancel()
    print("\n[D] 由同步函数执行（需独立事件循环）")
    test_http_smoke()
    print(f"\n==== RESULT: PASS={PASS} FAIL={FAIL} ====")
    print(f"临时数据目录: {_TMP}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
