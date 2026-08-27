"""Persistent background runner for legacy role pipelines and team DAGs."""
from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from typing import Any, Dict, Generator, List, Optional, Tuple

from . import agent_service, agent_teams, db

RUN_CANCEL: Dict[str, threading.Event] = {}
_RUN_THREADS: Dict[str, threading.Thread] = {}
APPROVAL_TIMEOUT = int(os.environ.get("AGENT_APPROVAL_TIMEOUT", "300"))
APPROVAL_POLL_INTERVAL = 0.6
_NO_DECISION = object()


async def submit_run(
    space_id: str,
    requirement: str,
    project_id: Optional[str] = None,
    roles: Optional[List[str]] = None,
    *,
    team_snapshot: Optional[Dict[str, Any]] = None,
    input_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Persist a run and immediately start its daemon worker."""
    run_id = str(uuid.uuid4())
    created = await db.database.create_agent_run(
        run_id, space_id, project_id, requirement, roles,
        team_id=team_snapshot.get("id") if team_snapshot else None,
        team_name=team_snapshot.get("name") if team_snapshot else None,
        team_snapshot=team_snapshot, input_context=input_context,
    )
    if not created:
        return ""
    if team_snapshot:
        await db.database.create_agent_run_nodes(run_id, space_id, team_snapshot["nodes"])
    await db.database.update_agent_run(run_id, space_id, started_at=int(time.time() * 1000))
    await db.database.add_agent_run_event(
        run_id, space_id, {"type": "run_start", "message": "Agent run started"})
    RUN_CANCEL[run_id] = threading.Event()
    _spawn(run_id, space_id, project_id, requirement, roles, team_snapshot, input_context)
    return run_id


async def cancel_run(run_id: str, space_id: str) -> bool:
    cancelled = await db.database.cancel_agent_run(run_id, space_id)
    if cancelled:
        signal = RUN_CANCEL.get(run_id)
        if signal is not None:
            signal.set()
        await db.database.cancel_pending_agent_run_nodes(run_id, space_id)
    return cancelled


def _spawn(run_id: str, space_id: str, project_id: Optional[str], requirement: str,
           roles: Optional[List[str]], team_snapshot: Optional[Dict[str, Any]],
           input_context: Optional[Dict[str, Any]]) -> None:
    worker = threading.Thread(
        target=_worker,
        args=(run_id, space_id, project_id, requirement, roles, team_snapshot, input_context),
        name=f"agent-run-{run_id[:8]}", daemon=True,
    )
    _RUN_THREADS[run_id] = worker
    worker.start()


def _worker(run_id: str, space_id: str, project_id: Optional[str], requirement: str,
            roles: Optional[List[str]], team_snapshot: Optional[Dict[str, Any]],
            input_context: Optional[Dict[str, Any]]) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_execute(
            run_id, space_id, project_id, requirement, roles, team_snapshot, input_context))
    except Exception as exc:  # pragma: no cover - final worker containment
        print(f"[agent_runner] worker crashed for {run_id}: {exc}")
    finally:
        loop.close()
        _RUN_THREADS.pop(run_id, None)


async def _execute(run_id: str, space_id: str, project_id: Optional[str], requirement: str,
                   roles: Optional[List[str]], team_snapshot: Optional[Dict[str, Any]],
                   input_context: Optional[Dict[str, Any]]) -> None:
    try:
        if team_snapshot:
            await _execute_dag(run_id, space_id, requirement, team_snapshot, input_context or {})
        else:
            await _execute_legacy(run_id, space_id, requirement, roles)
    except Exception as exc:  # noqa: BLE001 - persist all terminal failures
        await db.database.finish_agent_run(
            run_id, space_id, "failed",
            {"type": "error", "message": f"run failed: {exc}"},
            error_message=str(exc))
    finally:
        RUN_CANCEL.pop(run_id, None)


async def _is_cancelled(run_id: str, space_id: str) -> bool:
    signal = RUN_CANCEL.get(run_id)
    return bool((signal and signal.is_set()) or
                await db.database.get_agent_run_status(run_id, space_id) == "cancelled")


def _advance_generator(generator: Generator[Dict[str, Any], Any, None],
                       decision: object = _NO_DECISION) -> Tuple[bool, Optional[Dict[str, Any]]]:
    try:
        value = next(generator) if decision is _NO_DECISION else generator.send(decision)
        return True, value
    except StopIteration:
        return False, None


async def _drive_generator(run_id: str, space_id: str, phase: str,
                           generator: Generator[Dict[str, Any], Any, None],
                           node_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Drive one blocking LLM generator without blocking sibling DAG nodes."""
    alive, event = await asyncio.to_thread(_advance_generator, generator)
    last: Optional[Dict[str, Any]] = None
    while alive and event is not None:
        if await _is_cancelled(run_id, space_id):
            return None
        event_type = event.get("type")
        if event_type == "__approval_required":
            decision = await _handle_approval(
                run_id, space_id, RUN_CANCEL.get(run_id), event, node_id)
            alive, event = await asyncio.to_thread(_advance_generator, generator, decision)
            continue
        if event_type == "__replay":
            await db.database.append_agent_replay(
                run_id, space_id, node_id or event.get("phase", phase),
                int(event.get("round", 0)), event.get("messages", []))
        else:
            public_event = {**event}
            if node_id:
                public_event["nodeId"] = node_id
            await db.database.add_agent_run_event(run_id, space_id, public_event)
            if event_type == "complete":
                last = event
        alive, event = await asyncio.to_thread(_advance_generator, generator)
    return last


async def _execute_legacy(run_id: str, space_id: str, requirement: str,
                          roles: Optional[List[str]]) -> None:
    keys = roles or agent_service.load_role_config()
    if not keys:
        raise RuntimeError("no enabled roles")
    current_input = requirement
    summary: Dict[str, Any] = {}
    for index, key in enumerate(keys):
        if await _is_cancelled(run_id, space_id):
            await _finish_cancelled(run_id, space_id)
            return
        spec = agent_service.resolve_role(key)
        await db.database.add_agent_run_event(run_id, space_id, {
            "type": "phase_start", "phase": key, "label": spec["label"],
            "message": f"Phase {index + 1}: {spec['label']}",
        })
        last = await _drive_generator(
            run_id, space_id, key,
            agent_service.run_role(key, current_input, space_id=space_id))
        if await _is_cancelled(run_id, space_id):
            await _finish_cancelled(run_id, space_id)
            return
        if not last or not last.get("result", {}).get("success"):
            raise RuntimeError(f"{spec['label']} failed")
        current_input = last["result"]["raw_output"]
        summary[key] = last["result"]
    primary_output = summary[keys[-1]].get("structured") or summary[keys[-1]].get("raw_output")
    await db.database.finish_agent_run(
        run_id, space_id, "completed", {
            "type": "run_complete", "message": "Agent workflow completed", "summary": summary,
            "primaryOutput": primary_output,
        }, result_summary=summary)


async def _execute_dag(run_id: str, space_id: str, requirement: str,
                       team: Dict[str, Any], context: Dict[str, Any]) -> None:
    nodes = {node["id"]: node for node in team["nodes"]}
    predecessors: Dict[str, List[str]] = {node_id: [] for node_id in nodes}
    for edge in team["edges"]:  # list order is the fan-in prompt order
        predecessors[edge["target"]].append(edge["source"])
    statuses = {node_id: "pending" for node_id in nodes}
    results: Dict[str, Dict[str, Any]] = {}
    semaphore = asyncio.Semaphore(team.get("maxConcurrency", 2))
    available = {item["name"] for item in agent_teams.list_tool_capabilities()}
    for node in nodes.values():
        missing = [name for name in node.get("allowedTools", []) if name not in available]
        if missing:
            await db.database.add_agent_run_event(run_id, space_id, {
                "type": "node_warning", "nodeId": node["id"],
                "message": "Unavailable tools were removed", "tools": missing,
            })

    async def execute_node(node_id: str) -> Tuple[str, bool, Optional[Dict[str, Any]], str]:
        node = nodes[node_id]
        async with semaphore:
            if await _is_cancelled(run_id, space_id):
                await db.database.update_agent_run_node(
                    run_id, node_id, space_id, status="cancelled",
                    completed_at=int(time.time() * 1000))
                return node_id, False, None, "cancelled"
            statuses[node_id] = "running"
            await db.database.update_agent_run_node(
                run_id, node_id, space_id, status="running", started_at=int(time.time() * 1000))
            await db.database.add_agent_run_event(run_id, space_id, {
                "type": "node_start", "nodeId": node_id, "name": node["name"]})
            ordered_inputs = [(nodes[source], results[source]) for source in predecessors[node_id]]
            node_input = agent_teams.build_node_input(requirement, context, node, ordered_inputs)
            last = await _drive_generator(
                run_id, space_id, node_id,
                agent_service.run_node(
                    node, node_input, space_id, team.get("approvalMode", "manual")),
                node_id=node_id)
            if await _is_cancelled(run_id, space_id):
                await db.database.update_agent_run_node(
                    run_id, node_id, space_id, status="cancelled",
                    completed_at=int(time.time() * 1000))
                return node_id, False, None, "cancelled"
            completed = int(time.time() * 1000)
            if not last or not last.get("result", {}).get("success"):
                error = f"{node['name']} did not produce a valid result"
                await db.database.update_agent_run_node(
                    run_id, node_id, space_id, status="failed", error_message=error,
                    completed_at=completed)
                await db.database.add_agent_run_event(run_id, space_id, {
                    "type": "node_failed", "nodeId": node_id, "name": node["name"], "error": error})
                return node_id, False, None, error
            result = last["result"]
            normalized = {"text": result.get("raw_output", ""),
                          "structured": result.get("structured")}
            await db.database.update_agent_run_node(
                run_id, node_id, space_id, status="completed",
                text_output=normalized["text"], structured_output=normalized["structured"],
                completed_at=completed)
            await db.database.add_agent_run_event(run_id, space_id, {
                "type": "node_complete", "nodeId": node_id, "name": node["name"],
                "result": normalized})
            return node_id, True, normalized, ""

    while True:
        if await _is_cancelled(run_id, space_id):
            await _finish_cancelled(run_id, space_id)
            return
        ready = [node_id for node_id, status in statuses.items()
                 if status == "pending" and all(statuses[source] == "completed"
                                                for source in predecessors[node_id])]
        if not ready:
            break
        # Only queue work that can start now.  Creating tasks for every ready
        # node would let semaphore waiters begin after a sibling has failed,
        # even though the primary output can no longer succeed.
        ready = ready[:team.get("maxConcurrency", 2)]
        for node_id in ready:
            statuses[node_id] = "ready"
            await db.database.update_agent_run_node(run_id, node_id, space_id, status="ready")
            await db.database.add_agent_run_event(run_id, space_id, {
                "type": "node_queued", "nodeId": node_id, "name": nodes[node_id]["name"]})
        outcomes = await asyncio.gather(*(execute_node(node_id) for node_id in ready))
        batch_failed = False
        for node_id, success, result, error in outcomes:
            if success and result is not None:
                statuses[node_id] = "completed"
                results[node_id] = result
            elif error == "cancelled":
                statuses[node_id] = "cancelled"
            else:
                statuses[node_id] = "failed"
                batch_failed = True
        if batch_failed:
            break

    if await _is_cancelled(run_id, space_id):
        await _finish_cancelled(run_id, space_id)
        return
    for node_id, status in list(statuses.items()):
        if status == "pending":
            statuses[node_id] = "skipped"
            reason = "a predecessor failed or was skipped"
            await db.database.update_agent_run_node(
                run_id, node_id, space_id, status="skipped", error_message=reason,
                completed_at=int(time.time() * 1000))
            await db.database.add_agent_run_event(run_id, space_id, {
                "type": "node_skipped", "nodeId": node_id,
                "name": nodes[node_id]["name"], "reason": reason})

    output_id = team["outputNodeId"]
    summary = {node_id: result for node_id, result in results.items()}
    if statuses[output_id] != "completed":
        await db.database.finish_agent_run(
            run_id, space_id, "failed", {
                "type": "run_failed", "message": "Primary output node did not complete",
                "summary": summary,
            }, result_summary=summary, error_message="primary output node did not complete")
        return
    primary_output = results[output_id].get("structured")
    if primary_output is None:
        primary_output = results[output_id].get("text", "")
    await db.database.finish_agent_run(
        run_id, space_id, "completed", {
            "type": "run_complete", "message": "Expert team completed",
            "summary": summary, "primaryOutput": primary_output,
        }, result_summary=summary)


async def _finish_cancelled(run_id: str, space_id: str) -> None:
    await db.database.cancel_pending_agent_run_nodes(run_id, space_id)
    events = await db.database.get_agent_run_events(run_id, space_id)
    if not any(event["type"] == "run_cancelled" for event in events):
        await db.database.add_agent_run_event(
            run_id, space_id, {"type": "run_cancelled", "message": "Run cancelled"})
    await db.database.update_agent_run(
        run_id, space_id, status="cancelled", completed_at=int(time.time() * 1000))


async def _handle_approval(run_id: str, space_id: str,
                           cancel_signal: Optional[threading.Event], event: Dict[str, Any],
                           node_id: Optional[str] = None) -> bool:
    approval_id = event.get("approvalId") or str(uuid.uuid4())
    tool = event.get("tool") or "?"
    parameters = event.get("params") or {}
    await db.database.create_agent_tool_approval(
        approval_id, run_id, space_id, tool, parameters, node_id=node_id)
    await db.database.add_agent_run_event(run_id, space_id, {
        "type": "tool_approval", "approvalId": approval_id, "nodeId": node_id,
        "tool": tool, "parameters": parameters, "policy": event.get("policy", ""),
        "status": "pending", "message": f"Tool {tool} requires approval",
    })
    deadline = time.time() + APPROVAL_TIMEOUT
    while True:
        if (cancel_signal and cancel_signal.is_set()) or await _is_cancelled(run_id, space_id):
            await db.database.decide_agent_tool_approval(
                approval_id, run_id, space_id, status="cancelled")
            return False
        row = await db.database.get_agent_tool_approval(approval_id, run_id, space_id)
        if row and row["status"] in {"approved", "denied"}:
            approved = row["status"] == "approved"
            await db.database.add_agent_run_event(run_id, space_id, {
                "type": "tool_approval", "approvalId": approval_id, "nodeId": node_id,
                "tool": tool, "status": row["status"],
            })
            return approved
        if time.time() > deadline:
            await db.database.decide_agent_tool_approval(
                approval_id, run_id, space_id, status="timed_out")
            await db.database.add_agent_run_event(run_id, space_id, {
                "type": "tool_approval", "approvalId": approval_id, "nodeId": node_id,
                "tool": tool, "status": "timed_out",
            })
            return False
        await asyncio.sleep(APPROVAL_POLL_INTERVAL)


__all__ = ["submit_run", "cancel_run", "RUN_CANCEL"]
