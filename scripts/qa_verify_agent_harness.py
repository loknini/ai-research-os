#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent 工程能力验证脚本（对齐 DeepSeek Harness 的四项差距落地）。

隔离 DATA_DIR，真实 aiosqlite + 打桩 LLM（确定性），覆盖：

  A. 工具审批策略（单元级）：safe/sensitive/dangerous x auto/manual/strict 判定，
     execute() 的 fail-closed（无审批通道拒绝 / dangerous 非 strict 拦截）。
  B. Generator 审批暂停/恢复：run_role 遇到敏感工具 yield __approval_required，
     gen.send(True/False) 后继续至 complete；拒绝路径返回 blocked 结果。
  C. 可重放日志：append_agent_replay / get_agent_replay 往返一致；
     runner 端到端执行后 replay 非空（round 0 + 工具轮次均落库）。
  D. 上下文管理：estimate_tokens CJK 估算；compact_messages 摘要化早期历史、
     保留最近消息、切分点不破坏 tool 配对。
  E. 插件化：discover_tools 自动发现注册工具；get_tools 合并技能工具；
     execute 未知工具返回失败结果（不抛异常）。
  F. HTTP 冒烟（TestClient）：审批决策 API 全链路 —— 提交 run -> 审批 pending
     -> POST 决策 approved -> run 完成；GET /replay 返回结构。
"""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# 隔离数据目录（必须在 import backend.server 之前设置 DATA_DIR）
_TMP = tempfile.mkdtemp(prefix="qa_agent_harness_")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("LLM_BASE_URL", "http://127.0.0.1:9/none")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import backend.server as _bs  # noqa: F401
from backend.server import agent_service
from backend.server import tool_registry as reg
from backend.server import context as ctx
from scripts import database as db
import backend.server.agent_runner as agent_runner
from backend.server.agent_runner import submit_run

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


# ---------------- 打桩 LLM ----------------

def _install_llm_stub(script):
    """把 LLM 流式调用换成确定性脚本。

    ``script`` 为一个可调用对象，入参 ``(messages, call_index)``（**从 0 开始**），
    返回 ``(text_chunks, tool_calls)``：text_chunks 是 str 列表，tool_calls 是
    ``[{"id":..., "name":..., "arguments": {...}}]`` 列表。
    """
    state = {"n": 0}

    def stream_llm(messages, tools=None, **_kw):
        n = state["n"]
        state["n"] += 1
        chunks, calls = script(messages, n)
        for c in chunks:
            yield c
        if calls:
            yield {"tool_calls": calls}

    agent_service.llm_client.stream_llm = stream_llm
    agent_service.PARSERS = {"design": lambda t: None, "plan": lambda t: None}


def _final_answer_script(messages, n):
    return [json.dumps({"success": True, "raw_output": "fake-final"})], []


# ---------------- A. 审批策略 ----------------

def test_approval_policy():
    print("\n[A] 工具审批策略判定（单元级）")
    old_mode = os.environ.get("AGENT_APPROVAL_MODE")
    old_override = os.environ.get("AGENT_REQUIRE_APPROVAL_TOOLS")

    try:
        # 注册一个临时 dangerous 工具用于策略测试
        calls = []

        @reg.register_tool("__qa_dangerous", description="qa", policy=reg.POLICY_DANGEROUS)
        def _danger(params, space_id=None):
            calls.append(params)
            return {"success": True}

        os.environ.pop("AGENT_REQUIRE_APPROVAL_TOOLS", None)

        # safe 工具任何模式都不需要审批
        os.environ["AGENT_APPROVAL_MODE"] = "auto"
        check(reg.tool_needs_approval("fetch_papers") == (False, "safe"), "auto/safe -> 不需要审批")
        os.environ["AGENT_APPROVAL_MODE"] = "manual"
        check(reg.tool_needs_approval("fetch_papers") == (False, "safe"), "manual/safe -> 不需要审批")

        # sensitive 工具：auto 直通，manual/strict 等待审批
        os.environ["AGENT_APPROVAL_MODE"] = "auto"
        check(reg.tool_needs_approval("create_task") == (False, "sensitive"), "auto/sensitive -> 直接执行")
        os.environ["AGENT_APPROVAL_MODE"] = "manual"
        needed, pol = reg.tool_needs_approval("create_task")
        check(needed is True and pol == "sensitive", "manual/sensitive -> 等待审批")
        os.environ["AGENT_APPROVAL_MODE"] = "strict"
        check(reg.tool_needs_approval("create_task")[0] is True, "strict/sensitive -> 等待审批")

        # dangerous：非 strict 直接拦截（fail-closed），strict 等待审批
        os.environ["AGENT_APPROVAL_MODE"] = "auto"
        r = reg.execute("__qa_dangerous", {"x": 1})
        check(r.get("blocked") is True and r.get("success") is False, "auto/dangerous -> 拦截（fail-closed）")
        os.environ["AGENT_APPROVAL_MODE"] = "manual"
        check(reg.execute("__qa_dangerous", {"x": 1}).get("blocked") is True, "manual/dangerous -> 拦截")
        os.environ["AGENT_APPROVAL_MODE"] = "strict"
        needed = reg.tool_needs_approval("__qa_dangerous")[0]
        check(needed is True, "strict/dangerous -> 等待审批")
        # strict + approve 回调 -> 执行
        ok = reg.execute("__qa_dangerous", {"x": 2}, approve=lambda n, p: True)
        check(ok.get("success") is True and calls == [{"x": 2}], "strict/dangerous + 批准 -> 执行")
        # strict + approve 拒绝 -> 拦截
        r = reg.execute("__qa_dangerous", {"x": 3}, approve=lambda n, p: False)
        check(r.get("denied") is True, "strict/dangerous + 拒绝 -> denied")

        # 无审批通道（Chat 场景）：manual/sensitive fail-closed
        os.environ["AGENT_APPROVAL_MODE"] = "manual"
        r = reg.execute("create_task", {"title": "x"}, approve=None)
        check(r.get("blocked") is True and "未提供审批通道" in r.get("message", ""),
              "manual/sensitive 无审批通道 -> fail-closed 拒绝")

        # 单工具覆盖：auto 下强制审批
        os.environ["AGENT_APPROVAL_MODE"] = "auto"
        os.environ["AGENT_REQUIRE_APPROVAL_TOOLS"] = "create_note"
        check(reg.tool_needs_approval("create_note")[0] is True,
              "AGENT_REQUIRE_APPROVAL_TOOLS 覆盖 auto -> 强制审批")
        check(reg.tool_needs_approval("create_task")[0] is False,
              "覆盖名单外工具不受影响")
    finally:
        if old_mode:
            os.environ["AGENT_APPROVAL_MODE"] = old_mode
        else:
            os.environ.pop("AGENT_APPROVAL_MODE", None)
        if old_override:
            os.environ["AGENT_REQUIRE_APPROVAL_TOOLS"] = old_override
        else:
            os.environ.pop("AGENT_REQUIRE_APPROVAL_TOOLS", None)
        reg._REGISTRY.pop("__qa_dangerous", None)


# ---------------- B. Generator 审批暂停/恢复 ----------------

def test_generator_approval():
    print("\n[B] run_role 生成器审批暂停/恢复（拒绝路径）")

    def script(messages, n):
        if n == 0:
            # 第 1 次调用：请求调用敏感工具 create_task
            return [], [{"id": "call_1", "name": "create_task", "arguments": {"title": "审批测试任务"}}]
        # 第 2 次调用（工具结果已回灌）：直接给最终回答
        return [json.dumps({"success": True, "raw_output": "done-after-reject"})], []

    _install_llm_stub(script)
    os.environ["AGENT_APPROVAL_MODE"] = "manual"

    gen = agent_service.run_role("architect", "帮我建一个任务", space_id="qa")
    ev = next(gen)
    approvals = []
    decisions = [False]  # 拒绝
    while True:
        t = ev.get("type")
        if t == "__approval_required":
            approvals.append(ev)
            ev = gen.send(decisions.pop(0) if decisions else False)
        elif t == "complete":
            break
        else:
            try:
                ev = next(gen)
            except StopIteration:
                ev = None
            if ev is None:
                break

    check(len(approvals) == 1, f"触发一次 __approval_required（实际 {len(approvals)}）")
    if approvals:
        a = approvals[0]
        check(a.get("tool") == "create_task", f"审批目标工具 = create_task（实际 {a.get('tool')}）")
        check(a.get("approvalId") and len(a["approvalId"]) > 8, "审批事件含 approvalId")
        check(a.get("policy") == "sensitive", f"审批事件含 policy=sensitive（实际 {a.get('policy')}）")
        check(a.get("params", {}).get("title") == "审批测试任务", "审批事件携带工具参数")

    # 拒绝路径：工具结果应含 blocked/denied，且最终产出 complete
    os.environ.pop("AGENT_APPROVAL_MODE", None)


def test_generator_approval_approve():
    print("\n[B2] run_role 生成器审批（批准路径）")

    def script(messages, n):
        if n == 0:
            return [], [{"id": "call_2", "name": "create_task", "arguments": {"title": "审批通过任务"}}]
        # 第 2 次调用检查工具结果已回灌
        roles = [m.get("role") for m in messages]
        has_tool = "tool" in roles
        return [json.dumps({"success": True, "raw_output": f"approved-ok tool_seen={has_tool}"})], []

    _install_llm_stub(script)
    os.environ["AGENT_APPROVAL_MODE"] = "manual"

    gen = agent_service.run_role("architect", "帮我建一个任务", space_id="qa")
    ev = next(gen)
    approvals = 0
    final_text = ""
    while True:
        t = ev.get("type")
        if t == "__approval_required":
            approvals += 1
            ev = gen.send(True)  # 批准
        elif t == "complete":
            final_text = (ev.get("result") or {}).get("raw_output", "")
            break
        else:
            try:
                ev = next(gen)
            except StopIteration:
                ev = None
            if ev is None:
                break

    check(approvals == 1, f"批准路径触发一次审批（实际 {approvals}）")
    check("approved-ok" in final_text and "tool_seen=True" in final_text,
          f"批准后工具结果已回灌给模型（final={final_text[:50]!r}）")
    os.environ.pop("AGENT_APPROVAL_MODE", None)


# ---------------- C. 可重放日志 ----------------

async def test_replay_db_roundtrip():
    print("\n[C] 可重放日志落库/取回")
    await db.init_db()
    rid = "replay-test-run"
    msgs0 = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "需求"},
    ]
    ok = await db.append_agent_replay(rid, "qa", "architect", 0, msgs0)
    check(ok is True, "append_agent_replay(round 0) 成功")
    msgs1 = [
        {"role": "assistant", "content": "我会调用工具",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "create_task", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": '{"success": true}'},
    ]
    await db.append_agent_replay(rid, "qa", "architect", 1, msgs1)
    got = await db.get_agent_replay(rid, "qa")
    check(len(got) == 4, f"取回 4 条（round0 2 条 + round1 2 条，实际 {len(got)}）")
    check(all(m["phase"] == "architect" for m in got), "全部 phase=architect")
    rounds = [m["round"] for m in got]
    check(rounds == sorted(rounds), "按 round 升序返回")
    tool_msg = [m for m in got if m["message"].get("role") == "tool"]
    check(len(tool_msg) == 1 and tool_msg[0]["message"].get("tool_call_id") == "c1",
          "tool 消息完整保留（tool_call_id 配对）")
    # 空间隔离
    check(await db.get_agent_replay(rid, "OTHER") == [], "错 space 取回为空")


async def test_replay_end_to_end():
    print("\n[C2] runner 端到端：完成后的 run 含可重放日志")

    def script(messages, n):
        if n == 0:
            return [], [{"id": "call_e2e", "name": "create_task", "arguments": {"title": "e2e"}}]
        return [json.dumps({"success": True, "raw_output": "e2e-done"})], []

    _install_llm_stub(script)
    os.environ["AGENT_APPROVAL_MODE"] = "auto"  # auto：sensitive 直接执行，聚焦重放

    rid = await submit_run("qa", "端到端重放需求", roles=["architect"])
    deadline = time.time() + 15
    while True:
        st = await db.get_agent_run_status(rid, "qa")
        if st in ("completed", "failed", "cancelled"):
            break
        if time.time() > deadline:
            break
        await asyncio.sleep(0.05)
    check(st == "completed", f"run 完成（实际 {st}）")
    replay = await db.get_agent_replay(rid, "qa")
    check(len(replay) >= 4, f"replay 非空且含初始+工具轮（{len(replay)} 条）")
    rounds = sorted({m["round"] for m in replay})
    check(0 in rounds, "round 0（初始消息）已落库")
    roles = {m["message"].get("role") for m in replay}
    check("tool" in roles, "工具结果消息已落库（tool 角色可见）")
    os.environ.pop("AGENT_APPROVAL_MODE", None)


# ---------------- D. 上下文管理 ----------------

def test_context():
    print("\n[D] 上下文管理（token 估算 + 摘要压缩）")
    # token 估算：接收消息列表；CJK 字符 ≈ 1 token
    n = ctx.estimate_tokens([{"role": "user", "content": "你好世界 Hello"}])
    check(isinstance(n, int) and n >= 5, f"estimate_tokens 返回整数且 ≥5（实际 {n}）")

    # 打桩摘要生成（避免真实 LLM 调用）
    _orig_summarize = ctx.summarize_history
    ctx.summarize_history = lambda prefix: "已完成的早期对话要点摘要"

    try:
        # 构造超预算消息：早期 history + 最近的 tool 配对
        messages = [
            {"role": "system", "content": "sys"},
        ]
        for i in range(8):
            messages.append({"role": "user", "content": f"用户问题 {i} " + "啊" * 200})
            messages.append({"role": "assistant", "content": f"回答 {i} " + "嗯" * 200})
        messages.append({"role": "assistant", "content": "调用工具",
                         "tool_calls": [{"id": "last_tool", "type": "function",
                                         "function": {"name": "create_task", "arguments": "{}"}}]})
        messages.append({"role": "tool", "tool_call_id": "last_tool", "content": '{"success": true}'})

        compacted, compressed = ctx.compact_messages(messages, limit=600, keep_last=4)
        check(compressed is True, "超预算触发压缩")
        check(len(compacted) < len(messages), f"消息数减少（{len(messages)} -> {len(compacted)}）")
        # 最近 4 条（tool 配对）必须完整保留：tail 应与原尾部一致
        check(compacted[-2:] == messages[-2:], "最近 tool 配对完整保留（切分不破坏配对）")
        # 早期历史被摘要化
        has_summary = any(
            isinstance(m.get("content"), str) and "摘要" in m["content"]
            for m in compacted if m["role"] == "system"
        )
        check(has_summary, "早期历史被摘要化（system 摘要注入）")
        # 不超预算时不压缩
        small = [{"role": "user", "content": "hi"}]
        c2, comp2 = ctx.compact_messages(small, limit=100000)
        check(comp2 is False and c2 == small, "未超预算不压缩、消息原样返回")
        # 找不到干净切分点时不压缩（全 tool 配对被保护）
        weird = [{"role": "system", "content": "s"}] + [
            {"role": "assistant", "content": "a",
             "tool_calls": [{"id": f"t{i}", "type": "function", "function": {"name": "x", "arguments": "{}"}}]}
            for i in range(10)
        ]
        c3, comp3 = ctx.compact_messages(weird, limit=10, keep_last=4)
        check(comp3 is False and c3 == weird, "无干净 user 边界时不压缩（保护 tool 配对）")
    finally:
        ctx.summarize_history = _orig_summarize


# ---------------- E. 插件化 ----------------

def test_plugins():
    print("\n[E] 插件化（自动发现 + 合并 + 未知工具）")
    specs = {s.name: s for s in reg.list_specs()}
    for expected in ("fetch_papers", "create_task", "create_project", "create_note", "get_stats"):
        check(expected in specs, f"discover_tools 自动发现 {expected}")
    # 策略标注正确
    check(specs["fetch_papers"].policy == reg.POLICY_SAFE, "fetch_papers policy=safe")
    check(specs["create_task"].policy == reg.POLICY_SENSITIVE, "create_task policy=sensitive")

    tools = reg.get_tools()
    names = {t["function"]["name"] for t in tools}
    check("fetch_papers" in names, "注册表工具进入 function-calling schema")
    skill_names = {n for n in names if reg.is_skill_tool(n)}
    check(len(skill_names) >= 1, f"技能工具已合并（{sorted(skill_names)[:3]}…）")

    r = reg.execute("no_such_tool_xyz", {})
    check(r.get("success") is False and "未知工具" in r.get("message", ""),
          "未知工具返回失败结果（不抛异常）")


# ---------------- F. HTTP 冒烟（审批全链路） ----------------

def test_http_approval_flow():
    print("\n[F] HTTP 审批全链路（TestClient）")
    try:
        from fastapi.testclient import TestClient
        from backend.server.main import app
    except Exception as exc:  # noqa: BLE001
        check(False, f"导入 FastAPI app 失败：{exc}")
        return

    def script(messages, n):
        if n == 0:
            return [], [{"id": "call_http", "name": "create_task", "arguments": {"title": "http 审批"}}]
        return [json.dumps({"success": True, "raw_output": "http-approved-done"})], []

    _install_llm_stub(script)
    os.environ["AGENT_APPROVAL_MODE"] = "manual"

    H = {"X-Space-Key": "qaharness"}
    with TestClient(app) as client:
        resp = client.post("/api/agent/runs", json={"requirement": "HTTP 审批需求", "roles": ["architect"]}, headers=H)
        check(resp.status_code == 200, "POST /api/agent/runs -> 200")
        rid = resp.json().get("runId")
        check(bool(rid), f"返回 runId（{rid}）")
        if not rid:
            return

        # 轮询直到出现 pending 审批
        approval_id = None
        for _ in range(200):
            j = client.get(f"/api/agent/runs/{rid}", headers=H).json()
            pending = j.get("pendingApprovals") or []
            if pending:
                approval_id = pending[0]["id"]
                check(j.get("run", {}).get("status") == "running", "审批等待期间 run 仍 running")
                check(pending[0]["tool"] == "create_task", f"pending 审批工具正确（{pending[0]['tool']}）")
                break
            time.sleep(0.05)
        check(approval_id is not None, "审批行进入 pending（runner 暂停等待决策）")
        if not approval_id:
            return

        # 重复决策校验：先拒绝，验证非 pending 不可再决策
        r1 = client.post(f"/api/agent/runs/{rid}/approvals/{approval_id}",
                         json={"approved": False}, headers=H)
        check(r1.status_code == 200 and r1.json().get("success"), "POST 审批决策（拒绝）成功")
        r2 = client.post(f"/api/agent/runs/{rid}/approvals/{approval_id}",
                         json={"approved": True}, headers=H)
        check(r2.json().get("success") is False, "已决策审批不可重复决策")

        # run 应继续并完成（拒绝路径 -> 模型第二轮直接给最终回答）
        final = None
        for _ in range(200):
            j = client.get(f"/api/agent/runs/{rid}", headers=H).json()
            final = j.get("run", {}).get("status")
            if final in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.05)
        check(final == "completed", f"审批拒绝后 run 恢复并完成（实际 {final}）")

        # 审批历史 + 回放
        approvals = client.get(f"/api/agent/runs/{rid}/approvals", headers=H).json()
        check(approvals.get("success") and len(approvals.get("approvals", [])) == 1,
              f"GET /approvals 返回 1 条历史（实际 {len(approvals.get('approvals', []))}）")
        if approvals.get("approvals"):
            st = approvals["approvals"][0]["status"]
            check(st == "denied", f"审批终态 denied（实际 {st}）")

        replay = client.get(f"/api/agent/runs/{rid}/replay", headers=H).json()
        check(replay.get("success") and len(replay.get("replay", [])) >= 2,
              f"GET /replay 返回可重放日志（{len(replay.get('replay', []))} 条）")

        # 审批全链路通过后再跑一次「批准」路径
        def script2(messages, n):
            if n == 0:
                return [], [{"id": "call_http2", "name": "create_task", "arguments": {"title": "http 批准"}}]
            return [json.dumps({"success": True, "raw_output": "http-approved-yes"})], []

        _install_llm_stub(script2)
        resp2 = client.post("/api/agent/runs", json={"requirement": "HTTP 批准需求", "roles": ["architect"]}, headers=H)
        rid2 = resp2.json().get("runId")
        aid2 = None
        for _ in range(200):
            j = client.get(f"/api/agent/runs/{rid2}", headers=H).json()
            p = j.get("pendingApprovals") or []
            if p:
                aid2 = p[0]["id"]
                break
            time.sleep(0.05)
        check(aid2 is not None, "批准链路：审批行 pending")
        if aid2:
            client.post(f"/api/agent/runs/{rid2}/approvals/{aid2}", json={"approved": True}, headers=H)
        final2 = None
        for _ in range(200):
            j = client.get(f"/api/agent/runs/{rid2}", headers=H).json()
            final2 = j.get("run", {}).get("status")
            if final2 in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.05)
        check(final2 == "completed", f"批准后 run 完成（实际 {final2}）")
        # 批准路径下 create_task 真正写库
        tasks = client.get("/api/tasks", headers=H).json()
        titles = [t.get("title") for t in (tasks.get("tasks") or [])]
        check("http 批准" in titles, f"批准后 create_task 真正写库（titles={titles}）")

    os.environ.pop("AGENT_APPROVAL_MODE", None)


async def main():
    await db.init_db()
    test_approval_policy()
    test_generator_approval()
    test_generator_approval_approve()
    await test_replay_db_roundtrip()
    await test_replay_end_to_end()
    test_context()
    test_plugins()
    print("\n[F] 由同步函数执行（需独立事件循环）")
    test_http_approval_flow()
    print(f"\n==== RESULT: PASS={PASS} FAIL={FAIL} ====")
    print(f"临时数据目录: {_TMP}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
