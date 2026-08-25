"""后台非阻塞 Agent runner（Phase 2：多通道 / 持久 / 不阻塞请求）。

设计要点
--------
* ``run_full_workflow`` / ``run_role`` 是 **同步阻塞** 的生成器（内部 LLM 调用为
  urllib 同步请求）。若直接放进 FastAPI 请求协程会卡死事件循环，因此这里把
  整个执行搬到一个 **守护线程**，线程内自建 asyncio 事件循环去跑 DB 写操作。
* 每一帧事件 **立即落库** 到 ``aiosqlite``（``agent_runs`` / ``agent_run_events``，
  已按 space_id 隔离 + WAL），所以：
  - 提交接口 ``submit_run`` 立即返回 ``run_id``，**请求不阻塞**；
  - 前端用 ``GET /runs/{id}`` 轮询，或 ``GET /runs/{id}/stream`` 订阅 SSE；
  - 由于状态/事件都在共享 SQLite 里，天然 **跨多 worker 可见**（本服务以
    ``--workers N`` 部署，单进程内存态不可跨 worker 共享，故一切以 DB 为准）。
* 取消：内存 ``threading.Event`` 负责同 worker 即时打断；同时把状态写为
  ``cancelled`` 落库，后台线程每阶段前再读库确认，从而 **跨 worker 也能取消**。
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from . import agent_service  # backend/server/agent_service.py（同包，正规相对导入）
from . import db  # backend.server.db（同包，不要写成 from ..）

# 运行期持有的取消信号（同 worker 内即时生效）；跨 worker 以 DB 状态为准。
RUN_CANCEL: Dict[str, threading.Event] = {}

# 后台线程引用（便于调试/测试时 join）；不用于业务判断。
_RUN_THREADS: Dict[str, threading.Thread] = {}

# 审批等待超时（秒）与轮询间隔（秒）
APPROVAL_TIMEOUT = int(os.environ.get("AGENT_APPROVAL_TIMEOUT", "300"))
APPROVAL_POLL_INTERVAL = 0.6


async def submit_run(
    space_id: str,
    requirement: str,
    project_id: Optional[str] = None,
    roles: Optional[List[str]] = None,
) -> str:
    """提交一次后台 Agent 运行：落库即返回 run_id，执行在守护线程异步推进。"""
    run_id = str(uuid.uuid4())
    await db.database.create_agent_run(run_id, space_id, project_id, requirement, roles)
    RUN_CANCEL[run_id] = threading.Event()
    _spawn(run_id, space_id, project_id, requirement, roles)
    return run_id


async def cancel_run(run_id: str, space_id: str) -> bool:
    """取消一次运行：同 worker 置 Event，并落库（跨 worker 也生效）。"""
    ev = RUN_CANCEL.get(run_id)
    if ev is not None:
        ev.set()
    return await db.database.cancel_agent_run(run_id, space_id)


def _spawn(run_id: str, space_id: str, project_id: Optional[str],
           requirement: str, roles: Optional[List[str]]) -> None:
    """启动守护线程执行运行（线程内自建事件循环，避免污染主事件循环）。"""
    t = threading.Thread(
        target=_worker,
        args=(run_id, space_id, project_id, requirement, roles),
        name=f"agent-run-{run_id[:8]}",
        daemon=True,
    )
    _RUN_THREADS[run_id] = t
    t.start()


def _worker(run_id: str, space_id: str, project_id: Optional[str],
            requirement: str, roles: Optional[List[str]]) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_execute(run_id, space_id, project_id, requirement, roles))
    except Exception as exc:  # noqa: BLE001 - 兜底，避免线程静默崩
        print(f"[agent_runner] worker crashed for {run_id}: {exc}")
    finally:
        loop.close()
        _RUN_THREADS.pop(run_id, None)


async def _execute(run_id: str, space_id: str, project_id: Optional[str],
                   requirement: str, roles: Optional[List[str]]) -> None:
    """实际执行角色管线，逐帧落库；处理取消 / 异常 / 完成三态。

    消费 ``run_role`` 时使用 ``next()`` / ``send()`` 手动推进，以便处理两类
    内部事件：
    * ``__approval_required`` —— 落审批行 + 发 SSE 事件，然后**异步轮询等待**
      用户决策（approved/denied/超时/取消），把 bool 回传给生成器；
    * ``__replay`` —— 把该轮模型实际看到的完整消息序列落库（可重放日志）。
    """
    cancel_ev = RUN_CANCEL.get(run_id)
    now = int(time.time() * 1000)
    await db.database.update_agent_run(run_id, space_id, started_at=now)
    await db.database.add_agent_run_event(
        run_id, space_id, {"type": "run_start", "message": "已提交，后台 Agent 协作执行中…"})

    try:
        keys = roles or agent_service.load_role_config()
        if not keys:
            await db.database.add_agent_run_event(
                run_id, space_id, {"type": "error", "message": "没有启用的角色"})
            await db.database.update_agent_run(
                run_id, space_id, status="failed", completed_at=int(time.time() * 1000))
            return

        current_input = requirement
        summary: Dict[str, Any] = {}
        cancelled = False

        for idx, key in enumerate(keys):
            # 每阶段前双重确认取消：内存 Event（同 worker）+ DB 状态（跨 worker）
            status = await db.database.get_agent_run_status(run_id, space_id)
            if (cancel_ev is not None and cancel_ev.is_set()) or status == "cancelled":
                cancelled = True
                break

            spec = agent_service.resolve_role(key)
            await db.database.add_agent_run_event(run_id, space_id, {
                "type": "phase_start",
                "phase": key,
                "label": spec["label"],
                "message": f"=== Phase {idx + 1}: {spec['label']} ===",
            })

            last = None
            try:
                gen = agent_service.run_role(key, current_input, space_id=space_id)
                try:
                    ev = next(gen)
                except StopIteration:
                    ev = None

                while ev is not None:
                    ev_type = ev.get("type")
                    if ev_type == "__approval_required":
                        # —— 工具审批：落库 + 事件 + 等待用户决策 ——
                        decision = await _handle_approval(run_id, space_id, cancel_ev, ev)
                        try:
                            ev = gen.send(decision)
                        except StopIteration:
                            break
                    elif ev_type == "__replay":
                        # —— 可重放日志：该轮完整消息序列落库 ——
                        await db.database.append_agent_replay(
                            run_id, space_id, ev.get("phase", key),
                            int(ev.get("round", 0)), ev.get("messages", []))
                        try:
                            ev = next(gen)
                        except StopIteration:
                            break
                    else:
                        if cancel_ev is not None and cancel_ev.is_set():
                            cancelled = True
                            break
                        await db.database.add_agent_run_event(run_id, space_id, ev)
                        if ev_type == "complete":
                            last = ev
                        try:
                            ev = next(gen)
                        except StopIteration:
                            break
            except Exception as exc:  # 角色内部未捕获的异常
                await db.database.add_agent_run_event(
                    run_id, space_id,
                    {"type": "error", "message": f"{spec['label']}抛出异常：{exc}"})
                await db.database.update_agent_run(
                    run_id, space_id, status="failed",
                    error_message=str(exc), completed_at=int(time.time() * 1000))
                return

            if cancelled:
                break

            if last is None or not last.get("result", {}).get("success"):
                await db.database.add_agent_run_event(
                    run_id, space_id,
                    {"type": "error", "message": f"{spec['label']}执行失败"})
                await db.database.update_agent_run(
                    run_id, space_id, status="failed", completed_at=int(time.time() * 1000))
                return

            current_input = last["result"]["raw_output"]
            summary[key] = last["result"]

        if cancelled:
            await db.database.add_agent_run_event(
                run_id, space_id, {"type": "run_cancelled", "message": "运行已被取消"})
            await db.database.update_agent_run(
                run_id, space_id, status="cancelled", completed_at=int(time.time() * 1000))
            return

        await db.database.add_agent_run_event(run_id, space_id, {
            "type": "run_complete",
            "message": "多 Agent 协作完成！",
            "summary": summary,
        })
        await db.database.update_agent_run(
            run_id, space_id, status="completed",
            result_summary=summary, completed_at=int(time.time() * 1000))

    except Exception as exc:  # noqa: BLE001 - 顶层兜底
        await db.database.add_agent_run_event(
            run_id, space_id, {"type": "error", "message": f"运行异常：{exc}"})
        await db.database.update_agent_run(
            run_id, space_id, status="failed",
            error_message=str(exc), completed_at=int(time.time() * 1000))
    finally:
        RUN_CANCEL.pop(run_id, None)


async def _handle_approval(run_id: str, space_id: str,
                           cancel_ev: Optional[threading.Event],
                           ev: Dict[str, Any]) -> bool:
    """处理一次 ``__approval_required`` 内部事件：落库 + 发事件 + 等待决策。

    返回用户决策：True（批准执行）/ False（拒绝或超时/取消）。
    """
    approval_id = ev.get("approvalId") or str(uuid.uuid4())
    tool = ev.get("tool") or "?"
    params = ev.get("params") or {}

    await db.database.create_agent_tool_approval(
        approval_id, run_id, space_id, tool, params)
    await db.database.add_agent_run_event(run_id, space_id, {
        "type": "tool_approval",
        "approvalId": approval_id,
        "tool": tool,
        "parameters": params,
        "policy": ev.get("policy", ""),
        "status": "pending",
        "message": f"工具 {tool} 需要你的审批",
    })

    # —— 等待决策（异步轮询 DB，天然跨 worker 可见） ——
    deadline = time.time() + APPROVAL_TIMEOUT
    while True:
        if cancel_ev is not None and cancel_ev.is_set():
            await db.database.decide_agent_tool_approval(
                approval_id, run_id, space_id, status="cancelled")
            await db.database.add_agent_run_event(run_id, space_id, {
                "type": "tool_approval", "approvalId": approval_id, "tool": tool,
                "status": "cancelled", "message": f"运行已取消，工具 {tool} 未执行",
            })
            return False

        run_status = await db.database.get_agent_run_status(run_id, space_id)
        if run_status == "cancelled":
            await db.database.decide_agent_tool_approval(
                approval_id, run_id, space_id, status="cancelled")
            return False

        row = await db.database.get_agent_tool_approval(approval_id, run_id, space_id)
        if row and row["status"] == "approved":
            await db.database.add_agent_run_event(run_id, space_id, {
                "type": "tool_approval", "approvalId": approval_id, "tool": tool,
                "status": "approved", "message": f"已批准工具 {tool} 执行",
            })
            return True
        if row and row["status"] == "denied":
            await db.database.add_agent_run_event(run_id, space_id, {
                "type": "tool_approval", "approvalId": approval_id, "tool": tool,
                "status": "denied", "message": f"已拒绝工具 {tool} 的调用",
            })
            return False

        if time.time() > deadline:
            await db.database.decide_agent_tool_approval(
                approval_id, run_id, space_id, status="timed_out")
            await db.database.add_agent_run_event(run_id, space_id, {
                "type": "tool_approval", "approvalId": approval_id, "tool": tool,
                "status": "timed_out", "message": f"工具 {tool} 审批超时，已按拒绝处理",
            })
            return False

        await asyncio.sleep(APPROVAL_POLL_INTERVAL)


__all__ = ["submit_run", "cancel_run", "RUN_CANCEL"]
