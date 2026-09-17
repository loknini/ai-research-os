"""Agents persistence repository."""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from ..core import (
    DEFAULT_SPACE,
    _clean_text_for_db,
    _fetchall,
    _fetchone,
    get_db,
    with_busy_retry,
)

def _session_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将 agent_sessions 行转换为前端契约所需的 camelCase 字典。"""
    return {
        'id': row['id'],
        'projectId': row['project_id'],
        'sessionType': row['session_type'],
        'status': row['status'],
        'progress': row['progress'],
        'currentStep': row['current_step'],
        'inputData': json.loads(row['input_data']) if row['input_data'] else None,
        'outputData': json.loads(row['output_data']) if row['output_data'] else None,
        'startedAt': row['started_at'],
        'completedAt': row['completed_at'],
        'errorMessage': row['error_message'],
    }


async def create_agent_session(project_id: Optional[str], session_type: str,
                               input_data: Any = None, status: str = 'running',
                               space_id: str = DEFAULT_SPACE) -> Dict[str, Any]:
    """创建一条 Agent 会话记录（按空间打标）并返回 camelCase 字典。"""
    try:
        now = int(time.time() * 1000)
        session_id = str(uuid.uuid4())
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO agent_sessions
                (id, project_id, session_type, status, input_data, progress, current_step, started_at, completed_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id, project_id, session_type, status,
                json.dumps(input_data or {}, ensure_ascii=False), 0, '', now, None, space_id))
        return {
            'id': session_id, 'projectId': project_id, 'sessionType': session_type,
            'status': status, 'progress': 0, 'currentStep': '',
            'inputData': input_data, 'startedAt': now, 'completedAt': None,
        }
    except Exception as e:
        print(f"Create agent session error: {e}")
        return {}


async def get_agent_sessions(project_id: Optional[str] = None, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """列出某空间 Agent 会话（可按项目过滤）。"""
    async with get_db() as conn:
        if project_id:
            rows = await _fetchall(
                conn,
                'SELECT * FROM agent_sessions WHERE project_id = ? AND space_id = ? ORDER BY started_at DESC',
                (project_id, space_id))
        else:
            rows = await _fetchall(
                conn, 'SELECT * FROM agent_sessions WHERE space_id = ? ORDER BY started_at DESC', (space_id,))
        return [_session_to_dict(row) for row in rows]


async def get_agent_session(session_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 id 获取单条 Agent 会话（按空间过滤）。"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM agent_sessions WHERE id = ? AND space_id = ?', (session_id, space_id))
        return _session_to_dict(row) if row else None


async def update_agent_session(session_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新 Agent 会话（按空间校验）。"""
    allowed = {'status', 'progress', 'currentStep', 'outputData', 'completedAt', 'errorMessage'}
    updates = {k: v for k, v in updates.items() if k in allowed}
    if not updates:
        return False
    field_map = {
        'currentStep': 'current_step', 'outputData': 'output_data',
        'completedAt': 'completed_at', 'errorMessage': 'error_message',
    }
    set_clauses: List[str] = []
    values: List[Any] = []
    for key, value in updates.items():
        db_key = field_map.get(key, key)
        if key in ('outputData',):
            value = json.dumps(value, ensure_ascii=False)
        set_clauses.append(f"{db_key} = ?")
        values.append(value)
    values.append(session_id)
    values.append(space_id)
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                f"UPDATE agent_sessions SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?", values)
        return cur.rowcount > 0
    except Exception as e:
        print(f"Update agent session error: {e}")
        return False


async def add_agent_message(session_id: str, event: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """将一条流式事件持久化为 agent_messages 行（按空间打标）。"""
    try:
        now = int(time.time() * 1000)
        msg_id = str(uuid.uuid4())
        agent_role = event.get('agent') or event.get('phase') or 'system'
        message_type = event.get('type') or 'output'
        content = event.get('message') or event.get('step') or ''
        step_name = event.get('step')
        metadata = {k: v for k, v in event.items()
                    if k not in ('agent', 'phase', 'type', 'message', 'step')}
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO agent_messages
                (id, session_id, agent_role, message_type, content, step_name, metadata, timestamp, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                msg_id, session_id, agent_role, message_type, content, step_name,
                json.dumps(metadata, ensure_ascii=False), now, space_id))
        return True
    except Exception as e:
        print(f"Add agent message error: {e}")
        return False


async def get_agent_messages(session_id: str, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间会话的全部消息（流式事件回放）。"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            'SELECT * FROM agent_messages WHERE session_id = ? AND space_id = ? ORDER BY timestamp ASC',
            (session_id, space_id))
        return [{
            'id': row['id'],
            'sessionId': row['session_id'],
            'agentRole': row['agent_role'],
            'messageType': row['message_type'],
            'content': row['content'],
            'stepName': row['step_name'],
            'metadata': json.loads(row['metadata']) if row['metadata'] else {},
            'timestamp': row['timestamp'],
        } for row in rows]


def _team_record_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    definition = json.loads(row['definition']) if row['definition'] else {}
    return {
        **definition,
        'id': row['id'],
        'name': row['name'],
        'description': row['description'] or '',
        'category': row['category'] or 'custom',
        'builtin': False,
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }


async def list_agent_teams(space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT * FROM agent_teams WHERE space_id = ? ORDER BY updated_at DESC',
            (space_id,))
        return [_team_record_to_dict(row) for row in rows]


async def get_agent_team(team_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    async with get_db() as conn:
        row = await _fetchone(
            conn, 'SELECT * FROM agent_teams WHERE id = ? AND space_id = ?',
            (team_id, space_id))
        return _team_record_to_dict(row) if row else None


async def create_agent_team(definition: Dict[str, Any], space_id: str = DEFAULT_SPACE,
                            team_id: Optional[str] = None) -> Dict[str, Any]:
    now = int(time.time() * 1000)
    team_id = team_id or str(uuid.uuid4())
    payload = {key: value for key, value in definition.items()
               if key not in {'id', 'builtin', 'createdAt', 'updatedAt'}}
    async with get_db() as conn:
        await conn.execute('''
            INSERT INTO agent_teams
            (id, space_id, name, description, category, definition, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (team_id, space_id, payload.get('name', ''), payload.get('description', ''),
              payload.get('category', 'custom'), json.dumps(payload, ensure_ascii=False), now, now))
    return await get_agent_team(team_id, space_id) or {}


async def update_agent_team(team_id: str, definition: Dict[str, Any],
                            space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    payload = {key: value for key, value in definition.items()
               if key not in {'id', 'builtin', 'createdAt', 'updatedAt'}}
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE agent_teams SET name = ?, description = ?, category = ?,
                definition = ?, updated_at = ? WHERE id = ? AND space_id = ?
        ''', (payload.get('name', ''), payload.get('description', ''), payload.get('category', 'custom'),
              json.dumps(payload, ensure_ascii=False), int(time.time() * 1000), team_id, space_id))
        if cur.rowcount <= 0:
            return None
    return await get_agent_team(team_id, space_id)


async def delete_agent_team(team_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    async with get_db() as conn:
        cur = await conn.execute(
            'DELETE FROM agent_teams WHERE id = ? AND space_id = ?', (team_id, space_id))
        return cur.rowcount > 0


def _role_template_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    definition = json.loads(row['definition']) if row['definition'] else {}
    return {
        **definition, 'id': row['id'], 'name': row['name'],
        'description': row['description'] or '', 'builtin': False,
        'createdAt': row['created_at'], 'updatedAt': row['updated_at'],
    }


async def list_agent_role_templates(space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT * FROM agent_role_templates WHERE space_id = ? ORDER BY updated_at DESC',
            (space_id,))
        return [_role_template_to_dict(row) for row in rows]


async def get_agent_role_template(template_id: str,
                                  space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    async with get_db() as conn:
        row = await _fetchone(conn,
            'SELECT * FROM agent_role_templates WHERE id = ? AND space_id = ?',
            (template_id, space_id))
        return _role_template_to_dict(row) if row else None


async def create_agent_role_template(definition: Dict[str, Any], space_id: str = DEFAULT_SPACE,
                                     template_id: Optional[str] = None) -> Dict[str, Any]:
    now = int(time.time() * 1000)
    template_id = template_id or str(uuid.uuid4())
    payload = {key: value for key, value in definition.items()
               if key not in {'id', 'builtin', 'createdAt', 'updatedAt'}}
    async with get_db() as conn:
        await conn.execute('''
            INSERT INTO agent_role_templates
            (id, space_id, name, description, definition, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (template_id, space_id, payload.get('name', ''), payload.get('description', ''),
              json.dumps(payload, ensure_ascii=False), now, now))
    return await get_agent_role_template(template_id, space_id) or {}


async def update_agent_role_template(template_id: str, definition: Dict[str, Any],
                                     space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    payload = {key: value for key, value in definition.items()
               if key not in {'id', 'builtin', 'createdAt', 'updatedAt'}}
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE agent_role_templates SET name = ?, description = ?, definition = ?, updated_at = ?
            WHERE id = ? AND space_id = ?
        ''', (payload.get('name', ''), payload.get('description', ''),
              json.dumps(payload, ensure_ascii=False), int(time.time() * 1000), template_id, space_id))
        if cur.rowcount <= 0:
            return None
    return await get_agent_role_template(template_id, space_id)


async def delete_agent_role_template(template_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    async with get_db() as conn:
        cur = await conn.execute(
            'DELETE FROM agent_role_templates WHERE id = ? AND space_id = ?',
            (template_id, space_id))
        return cur.rowcount > 0


def _run_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    """将 agent_runs 行转换为前端契约的 camelCase 字典。"""
    if not row:
        return {}
    keys = set(row.keys())
    def parsed(column: str) -> Any:
        return json.loads(row[column]) if column in keys and row[column] else None
    return {
        'id': row['id'],
        'spaceId': row['space_id'],
        'projectId': row['project_id'],
        'requirement': row['requirement'],
        'roles': json.loads(row['roles']) if row['roles'] else [],
        'teamId': row['team_id'],
        'teamName': row['team_name'],
        'teamSnapshot': json.loads(row['team_snapshot']) if row['team_snapshot'] else None,
        'inputContext': json.loads(row['input_context']) if row['input_context'] else None,
        'status': row['status'],
        'errorMessage': row['error_message'],
        'resultSummary': json.loads(row['result_summary']) if row['result_summary'] else None,
        'createdAt': row['created_at'],
        'startedAt': row['started_at'],
        'completedAt': row['completed_at'],
        'runKind': row['run_kind'] if 'run_kind' in keys else 'dag',
        'phase': row['phase'] if 'phase' in keys else None,
        'iteration': row['iteration'] if 'iteration' in keys else 0,
        'maxIterations': row['max_iterations'] if 'max_iterations' in keys else None,
        'deadlineAt': row['deadline_at'] if 'deadline_at' in keys else None,
        'workspaceSnapshot': parsed('workspace_snapshot'),
        'checkpoint': parsed('checkpoint'),
        'authorization': parsed('authorization'),
        'budgetUsedMs': row['budget_used_ms'] if 'budget_used_ms' in keys else 0,
    }


async def create_agent_run(run_id: str, space_id: str, project_id: Optional[str],
                           requirement: str, roles: Any = None, status: str = 'running',
                           team_id: Optional[str] = None, team_name: Optional[str] = None,
                           team_snapshot: Any = None, input_context: Any = None,
                           run_kind: str = 'dag', phase: Optional[str] = None,
                           max_iterations: Optional[int] = None,
                           deadline_at: Optional[int] = None,
                           workspace_snapshot: Any = None, checkpoint: Any = None,
                           authorization: Any = None) -> str:
    """创建一条后台 Agent 运行记录（按空间打标）并返回 run id。"""
    try:
        now = int(time.time() * 1000)
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO agent_runs
                (id, space_id, project_id, requirement, roles, status, created_at, started_at,
                 completed_at, team_id, team_name, team_snapshot, input_context,
                 run_kind, phase, max_iterations, deadline_at, workspace_snapshot,
                 checkpoint, authorization)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                run_id, space_id, project_id, requirement,
                json.dumps(roles or [], ensure_ascii=False), status, now, None, None,
                team_id, team_name,
                json.dumps(team_snapshot, ensure_ascii=False) if team_snapshot is not None else None,
                json.dumps(input_context, ensure_ascii=False) if input_context is not None else None,
                run_kind, phase, max_iterations, deadline_at,
                json.dumps(workspace_snapshot, ensure_ascii=False) if workspace_snapshot is not None else None,
                json.dumps(checkpoint, ensure_ascii=False) if checkpoint is not None else None,
                json.dumps(authorization, ensure_ascii=False) if authorization is not None else None))
        return run_id
    except Exception as e:
        print(f"Create agent run error: {e}")
        return ""


async def update_agent_run(run_id: str, space_id: str, status: Optional[str] = None,
                           error_message: Optional[str] = None,
                           result_summary: Any = None,
                           started_at: Optional[int] = None,
                           completed_at: Optional[int] = None,
                           phase: Optional[str] = None,
                           iteration: Optional[int] = None,
                           max_iterations: Optional[int] = None,
                           deadline_at: Optional[int] = None,
                           workspace_snapshot: Any = None,
                           checkpoint: Any = None,
                           authorization: Any = None,
                           budget_used_ms: Optional[int] = None,
                           lease_owner: Optional[str] = None,
                           lease_expires_at: Optional[int] = None) -> bool:
    """更新一条后台运行记录（按空间校验）。仅接受白名单字段。"""
    allowed = {
        'status', 'error_message', 'result_summary', 'started_at', 'completed_at',
        'phase', 'iteration', 'max_iterations', 'deadline_at', 'workspace_snapshot',
        'checkpoint', 'authorization', 'budget_used_ms', 'lease_owner', 'lease_expires_at',
    }
    updates = {
        'status': status, 'error_message': error_message,
        'result_summary': result_summary, 'started_at': started_at,
        'completed_at': completed_at, 'phase': phase, 'iteration': iteration,
        'max_iterations': max_iterations, 'deadline_at': deadline_at,
        'workspace_snapshot': workspace_snapshot, 'checkpoint': checkpoint,
        'authorization': authorization, 'budget_used_ms': budget_used_ms,
        'lease_owner': lease_owner, 'lease_expires_at': lease_expires_at,
    }
    updates = {k: v for k, v in updates.items() if v is not None and k in allowed}
    if not updates:
        return False
    set_clauses: List[str] = []
    values: List[Any] = []
    for key, value in updates.items():
        if key in {'result_summary', 'workspace_snapshot', 'checkpoint', 'authorization'}:
            value = json.dumps(value, ensure_ascii=False)
        set_clauses.append(f"{key} = ?")
        values.append(value)
    values.append(run_id)
    values.append(space_id)
    try:
        async with get_db() as conn:
            cur = await conn.execute(
                f"UPDATE agent_runs SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?", values)
        return cur.rowcount > 0
    except Exception as e:
        print(f"Update agent run error: {e}")
        return False


async def get_agent_run(run_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """根据 id 获取单条运行记录（按空间过滤）。"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM agent_runs WHERE id = ? AND space_id = ?', (run_id, space_id))
        return _run_to_dict(row) if row else None


async def get_agent_run_status(run_id: str, space_id: str = DEFAULT_SPACE) -> Optional[str]:
    """仅取运行状态（供后台线程跨 worker 轮询取消标志）。"""
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT status FROM agent_runs WHERE id = ? AND space_id = ?', (run_id, space_id))
        return row['status'] if row else None


async def add_agent_run_event(run_id: str, space_id: str, event: Dict[str, Any]) -> bool:
    """将一条运行事件持久化为 agent_run_events 行（按空间打标）。返回自增 id 由调用方无关。"""
    try:
        now = int(time.time() * 1000)
        event_type = event.get('type') or event.get('agent') or 'event'
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO agent_run_events (run_id, space_id, type, data, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (run_id, space_id, event_type, json.dumps(event, ensure_ascii=False), now))
        return True
    except Exception as e:
        print(f"Add agent run event error: {e}")
        return False


async def finish_agent_run(run_id: str, space_id: str, status: str,
                           event: Dict[str, Any], result_summary: Any = None,
                           error_message: Optional[str] = None) -> bool:
    """Atomically transition a live run and append exactly one terminal event.

    The guarded UPDATE prevents a late worker result from reviving a run after
    another worker (or the user) has cancelled it.
    """
    if status not in {'completed', 'failed'}:
        raise ValueError("finish_agent_run status must be completed or failed")
    now = int(time.time() * 1000)
    summary_json = (json.dumps(result_summary, ensure_ascii=False)
                    if result_summary is not None else None)
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE agent_runs SET status = ?, result_summary = COALESCE(?, result_summary),
                error_message = ?, completed_at = ?
            WHERE id = ? AND space_id = ? AND status IN ('pending', 'running')
        ''', (status, summary_json, error_message, now, run_id, space_id))
        if cur.rowcount <= 0:
            return False
        event_type = event.get('type') or status
        await conn.execute('''
            INSERT INTO agent_run_events (run_id, space_id, type, data, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (run_id, space_id, event_type, json.dumps(event, ensure_ascii=False), now))
        return True


async def get_agent_run_events(run_id: str, space_id: str = DEFAULT_SPACE,
                               after_id: int = 0) -> List[Dict[str, Any]]:
    """获取某运行、某空间的全部（或 after_id 之后的增量）事件，按 id 升序。"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            'SELECT * FROM agent_run_events WHERE run_id = ? AND space_id = ? AND id > ? ORDER BY id ASC',
            (run_id, space_id, after_id))
        return [{
            'id': row['id'],
            'runId': row['run_id'],
            'type': row['type'],
            'data': json.loads(row['data']) if row['data'] else {},
            'createdAt': row['created_at'],
        } for row in rows]


async def list_agent_runs(space_id: str = DEFAULT_SPACE, project_id: Optional[str] = None,
                          limit: int = 50) -> List[Dict[str, Any]]:
    """列出某空间的后台运行（可按项目过滤），按创建时间倒序。"""
    async with get_db() as conn:
        if project_id:
            rows = await _fetchall(
                conn,
                'SELECT * FROM agent_runs WHERE project_id = ? AND space_id = ? ORDER BY created_at DESC LIMIT ?',
                (project_id, space_id, limit))
        else:
            rows = await _fetchall(
                conn, 'SELECT * FROM agent_runs WHERE space_id = ? ORDER BY created_at DESC LIMIT ?',
                (space_id, limit))
        return [_run_to_dict(row) for row in rows]


async def cancel_agent_run(run_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """Atomically mark a live run cancelled and append its terminal event."""
    async with get_db() as conn:
        now = int(time.time() * 1000)
        cur = await conn.execute(
            "UPDATE agent_runs SET status = 'cancelled', completed_at = ? "
            "WHERE id = ? AND space_id = ? AND status IN ('pending', 'running')",
            (now, run_id, space_id))
        if cur.rowcount <= 0:
            return False
        event = {"type": "run_cancelled", "message": "Run cancelled"}
        await conn.execute('''
            INSERT INTO agent_run_events (run_id, space_id, type, data, created_at)
            VALUES (?, ?, 'run_cancelled', ?, ?)
        ''', (run_id, space_id, json.dumps(event, ensure_ascii=False), now))
        return True


async def claim_development_run(run_id: str, space_id: str, owner: str,
                                lease_ms: int = 30000) -> bool:
    """原子领取一条待执行/租约过期的研发运行。"""
    now = int(time.time() * 1000)
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE agent_runs SET lease_owner = ?, lease_expires_at = ?, status = 'running',
                started_at = COALESCE(started_at, ?)
            WHERE id = ? AND space_id = ? AND run_kind = 'development'
              AND status IN ('pending', 'running')
              AND (lease_owner IS NULL OR lease_owner = ? OR lease_expires_at IS NULL OR lease_expires_at < ?)
        ''', (owner, now + lease_ms, now, run_id, space_id, owner, now))
        return cur.rowcount > 0


async def renew_development_lease(run_id: str, space_id: str, owner: str,
                                  lease_ms: int = 30000) -> bool:
    now = int(time.time() * 1000)
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE agent_runs SET lease_expires_at = ?
            WHERE id = ? AND space_id = ? AND run_kind = 'development'
              AND status = 'running' AND lease_owner = ?
        ''', (now + lease_ms, run_id, space_id, owner))
        return cur.rowcount > 0


async def finish_development_run(run_id: str, space_id: str, owner: str,
                                 status: str, phase: str,
                                 result_summary: Any = None,
                                 error_message: Optional[str] = None) -> bool:
    now = int(time.time() * 1000)
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE agent_runs SET status = ?, phase = ?, result_summary = COALESCE(?, result_summary),
                error_message = ?, completed_at = ?, lease_owner = NULL, lease_expires_at = NULL
            WHERE id = ? AND space_id = ? AND run_kind = 'development' AND lease_owner = ?
              AND status = 'running'
        ''', (status, phase,
              json.dumps(result_summary, ensure_ascii=False) if result_summary is not None else None,
              error_message, now, run_id, space_id, owner))
        if cur.rowcount <= 0:
            return False
        event = {"type": "run_complete" if status == "completed" else "run_failed",
                 "phase": phase, "message": error_message or phase}
        await conn.execute('''
            INSERT INTO agent_run_events (run_id, space_id, type, data, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (run_id, space_id, event["type"], json.dumps(event, ensure_ascii=False), now))
        return True


async def continue_development_run(run_id: str, space_id: str,
                                   additional_iterations: int,
                                   additional_minutes: int,
                                   feedback: Optional[str] = None) -> bool:
    now = int(time.time() * 1000)
    async with get_db() as conn:
        row = await _fetchone(conn, '''
            SELECT max_iterations, deadline_at, checkpoint FROM agent_runs
            WHERE id = ? AND space_id = ? AND run_kind = 'development'
              AND status = 'failed' AND phase = 'budget_exhausted'
        ''', (run_id, space_id))
        if not row:
            return False
        checkpoint = json.loads(row['checkpoint']) if row['checkpoint'] else {}
        if feedback:
            previous = checkpoint.get('feedback') or ''
            checkpoint['feedback'] = (f"{previous}\n\n用户追加反馈：{feedback}" if previous else
                                      f"用户追加反馈：{feedback}")[-40000:]
        cur = await conn.execute('''
            UPDATE agent_runs SET status = 'pending', phase = 'queued', completed_at = NULL,
                error_message = NULL, max_iterations = ?, deadline_at = ?, checkpoint = ?,
                lease_owner = NULL, lease_expires_at = NULL
            WHERE id = ? AND space_id = ?
        ''', ((row['max_iterations'] or 0) + additional_iterations,
              max(now, row['deadline_at'] or now) + additional_minutes * 60 * 1000,
              json.dumps(checkpoint, ensure_ascii=False), run_id, space_id))
        return cur.rowcount > 0


async def list_claimable_development_runs(limit: int = 20) -> List[Dict[str, Any]]:
    now = int(time.time() * 1000)
    async with get_db() as conn:
        rows = await _fetchall(conn, '''
            SELECT * FROM agent_runs WHERE run_kind = 'development'
              AND status IN ('pending', 'running')
              AND (lease_owner IS NULL OR lease_expires_at IS NULL OR lease_expires_at < ?)
            ORDER BY created_at ASC LIMIT ?
        ''', (now, limit))
        return [_run_to_dict(row) for row in rows]


async def create_development_step(run_id: str, space_id: str, iteration: int,
                                  phase: str, stage_node_id: Optional[str] = None,
                                  input_summary: Optional[str] = None,
                                  attempt: int = 1) -> str:
    step_id = str(uuid.uuid4())
    now = int(time.time() * 1000)
    async with get_db() as conn:
        await conn.execute('''
            INSERT OR REPLACE INTO development_run_steps
            (id, run_id, space_id, iteration, phase, stage_node_id, attempt, status,
             input_summary, started_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)
        ''', (step_id, run_id, space_id, iteration, phase, stage_node_id,
              attempt, _clean_text_for_db(input_summary), now))
    return step_id


async def finish_development_step(step_id: str, run_id: str, space_id: str,
                                  status: str, output: Any = None,
                                  error_message: Optional[str] = None) -> bool:
    now = int(time.time() * 1000)
    output_text = (json.dumps(output, ensure_ascii=False)
                   if output is not None and not isinstance(output, str) else output)
    async with get_db() as conn:
        cur = await conn.execute('''
            UPDATE development_run_steps SET status = ?, output = ?, error_message = ?, completed_at = ?
            WHERE id = ? AND run_id = ? AND space_id = ?
        ''', (status, _clean_text_for_db(output_text), _clean_text_for_db(error_message),
              now, step_id, run_id, space_id))
        return cur.rowcount > 0


def _development_step_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    output: Any = row['output']
    if output:
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            pass
    return {
        'id': row['id'], 'runId': row['run_id'], 'iteration': row['iteration'],
        'phase': row['phase'], 'stageNodeId': row['stage_node_id'],
        'attempt': row['attempt'], 'status': row['status'],
        'inputSummary': row['input_summary'], 'output': output,
        'errorMessage': row['error_message'], 'startedAt': row['started_at'],
        'completedAt': row['completed_at'],
    }


async def list_development_steps(run_id: str, space_id: str) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        rows = await _fetchall(conn, '''
            SELECT * FROM development_run_steps WHERE run_id = ? AND space_id = ?
            ORDER BY iteration ASC, started_at ASC
        ''', (run_id, space_id))
        return [_development_step_to_dict(row) for row in rows]


async def add_development_artifact(run_id: str, space_id: str, iteration: int,
                                   kind: str, content: Optional[str] = None,
                                   relative_path: Optional[str] = None,
                                   metadata: Any = None) -> str:
    artifact_id = str(uuid.uuid4())
    async with get_db() as conn:
        await conn.execute('''
            INSERT INTO development_artifacts
            (id, run_id, space_id, iteration, kind, relative_path, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (artifact_id, run_id, space_id, iteration, kind, relative_path,
              _clean_text_for_db(content[:262144] if content else None),
              json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
              int(time.time() * 1000)))
    return artifact_id


async def list_development_artifacts(run_id: str, space_id: str) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        rows = await _fetchall(conn, '''
            SELECT * FROM development_artifacts WHERE run_id = ? AND space_id = ?
            ORDER BY created_at ASC
        ''', (run_id, space_id))
        return [{
            'id': row['id'], 'runId': row['run_id'], 'iteration': row['iteration'],
            'kind': row['kind'], 'relativePath': row['relative_path'],
            'content': row['content'],
            'metadata': json.loads(row['metadata']) if row['metadata'] else None,
            'createdAt': row['created_at'],
        } for row in rows]


def _run_node_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    return {
        'runId': row['run_id'], 'nodeId': row['node_id'], 'name': row['node_name'],
        'status': row['status'], 'textOutput': row['text_output'],
        'structuredOutput': json.loads(row['structured_output']) if row['structured_output'] else None,
        'errorMessage': row['error_message'], 'queuedAt': row['queued_at'],
        'startedAt': row['started_at'], 'completedAt': row['completed_at'],
    }


async def create_agent_run_nodes(run_id: str, space_id: str,
                                 nodes: List[Dict[str, Any]]) -> None:
    now = int(time.time() * 1000)
    async with get_db() as conn:
        for node in nodes:
            await conn.execute('''
                INSERT OR IGNORE INTO agent_run_nodes
                (run_id, node_id, space_id, node_name, status, queued_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
            ''', (run_id, node['id'], space_id, node.get('name', node['id']), now))


async def update_agent_run_node(run_id: str, node_id: str, space_id: str,
                                status: Optional[str] = None, text_output: Optional[str] = None,
                                structured_output: Any = None, error_message: Optional[str] = None,
                                started_at: Optional[int] = None,
                                completed_at: Optional[int] = None) -> bool:
    values_by_column = {
        'status': status, 'text_output': text_output,
        'structured_output': (json.dumps(structured_output, ensure_ascii=False)
                              if structured_output is not None else None),
        'error_message': error_message, 'started_at': started_at, 'completed_at': completed_at,
    }
    updates = {key: value for key, value in values_by_column.items() if value is not None}
    if not updates:
        return False
    assignments = ', '.join(f'{column} = ?' for column in updates)
    async with get_db() as conn:
        cur = await conn.execute(
            f'UPDATE agent_run_nodes SET {assignments} WHERE run_id = ? AND node_id = ? AND space_id = ?',
            (*updates.values(), run_id, node_id, space_id))
        return cur.rowcount > 0


async def list_agent_run_nodes(run_id: str,
                               space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        rows = await _fetchall(conn, '''
            SELECT * FROM agent_run_nodes WHERE run_id = ? AND space_id = ?
            ORDER BY queued_at ASC, node_id ASC
        ''', (run_id, space_id))
        return [_run_node_to_dict(row) for row in rows]


async def cancel_pending_agent_run_nodes(run_id: str, space_id: str,
                                         status: str = 'cancelled') -> None:
    async with get_db() as conn:
        await conn.execute('''
            UPDATE agent_run_nodes SET status = ?, completed_at = ?
            WHERE run_id = ? AND space_id = ? AND status IN ('pending', 'ready')
        ''', (status, int(time.time() * 1000), run_id, space_id))


def _approval_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    return {
        'id': row['id'],
        'runId': row['run_id'],
        'spaceId': row['space_id'],
        'tool': row['tool'],
        'nodeId': row['node_id'],
        'parameters': json.loads(row['parameters']) if row['parameters'] else {},
        'status': row['status'],
        'createdAt': row['created_at'],
        'decidedAt': row['decided_at'],
    }


async def create_agent_tool_approval(approval_id: str, run_id: str, space_id: str,
                                     tool: str, parameters: Any,
                                     node_id: Optional[str] = None) -> bool:
    """落一条 pending 审批记录，返回是否成功。"""
    try:
        now = int(time.time() * 1000)
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO agent_tool_approvals
                (id, run_id, space_id, tool, node_id, parameters, status, created_at, decided_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, NULL)
            ''', (approval_id, run_id, space_id, tool, node_id,
                  json.dumps(parameters, ensure_ascii=False), now))
        return True
    except Exception as e:
        print(f"Create agent tool approval error: {e}")
        return False


async def get_agent_tool_approval(approval_id: str, run_id: str,
                                  space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """按 id + 空间取一条审批记录（供 runner 轮询决策）。"""
    async with get_db() as conn:
        row = await _fetchone(
            conn,
            'SELECT * FROM agent_tool_approvals WHERE id = ? AND run_id = ? AND space_id = ?',
            (approval_id, run_id, space_id))
        return _approval_to_dict(row) if row else None


async def decide_agent_tool_approval(approval_id: str, run_id: str, space_id: str,
                                     approved: Optional[bool] = None,
                                     status: Optional[str] = None) -> bool:
    """对 pending 审批做决策：approved=True -> 'approved'，False -> 'denied'，
    或直接指定终态 status（'timed_out' / 'cancelled'）。仅 pending 时生效。"""
    if status is None:
        status = 'approved' if approved else 'denied'
    async with get_db() as conn:
        cur = await conn.execute(
            "UPDATE agent_tool_approvals SET status = ?, decided_at = ? "
            "WHERE id = ? AND run_id = ? AND space_id = ? AND status = 'pending'",
            (status, int(time.time() * 1000), approval_id, run_id, space_id))
        return cur.rowcount > 0


async def list_agent_tool_approvals(run_id: str, space_id: str = DEFAULT_SPACE,
                                    status: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出某运行的全部（或指定状态）审批记录，按创建时间升序。"""
    async with get_db() as conn:
        if status:
            rows = await _fetchall(
                conn,
                'SELECT * FROM agent_tool_approvals WHERE run_id = ? AND space_id = ? AND status = ? ORDER BY created_at ASC',
                (run_id, space_id, status))
        else:
            rows = await _fetchall(
                conn,
                'SELECT * FROM agent_tool_approvals WHERE run_id = ? AND space_id = ? ORDER BY created_at ASC',
                (run_id, space_id))
        return [_approval_to_dict(row) for row in rows]


async def append_agent_replay(run_id: str, space_id: str, phase: str, round_: int,
                              messages: List[Dict[str, Any]]) -> bool:
    """把某一轮「模型实际看到的消息序列」逐条落库（含 tool_calls 结构）。"""
    try:
        now = int(time.time() * 1000)
        async with get_db() as conn:
            for m in messages:
                await conn.execute('''
                    INSERT INTO agent_replay_messages (run_id, space_id, phase, round, role, content, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (run_id, space_id, phase, round_, m.get('role', 'user'),
                      json.dumps(m, ensure_ascii=False), now))
        return True
    except Exception as e:
        print(f"Append agent replay error: {e}")
        return False


async def get_agent_replay(run_id: str, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """按 (phase, round, id) 顺序取回完整重放消息，供前端会话回放。"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn,
            'SELECT * FROM agent_replay_messages WHERE run_id = ? AND space_id = ? '
            'ORDER BY phase, round ASC, id ASC',
            (run_id, space_id))
        return [{
            'id': row['id'],
            'runId': row['run_id'],
            'phase': row['phase'],
            'round': row['round'],
            'role': row['role'],
            'message': json.loads(row['content']) if row['content'] else {},
            'createdAt': row['created_at'],
        } for row in rows]


__all__ = [
    "_session_to_dict",
    "create_agent_session",
    "get_agent_sessions",
    "get_agent_session",
    "update_agent_session",
    "add_agent_message",
    "get_agent_messages",
    "_team_record_to_dict",
    "list_agent_teams",
    "get_agent_team",
    "create_agent_team",
    "update_agent_team",
    "delete_agent_team",
    "_role_template_to_dict",
    "list_agent_role_templates",
    "get_agent_role_template",
    "create_agent_role_template",
    "update_agent_role_template",
    "delete_agent_role_template",
    "_run_to_dict",
    "create_agent_run",
    "update_agent_run",
    "get_agent_run",
    "get_agent_run_status",
    "add_agent_run_event",
    "finish_agent_run",
    "get_agent_run_events",
    "list_agent_runs",
    "cancel_agent_run",
    "claim_development_run",
    "renew_development_lease",
    "finish_development_run",
    "continue_development_run",
    "list_claimable_development_runs",
    "create_development_step",
    "finish_development_step",
    "_development_step_to_dict",
    "list_development_steps",
    "add_development_artifact",
    "list_development_artifacts",
    "_run_node_to_dict",
    "create_agent_run_nodes",
    "update_agent_run_node",
    "list_agent_run_nodes",
    "cancel_pending_agent_run_nodes",
    "_approval_to_dict",
    "create_agent_tool_approval",
    "get_agent_tool_approval",
    "decide_agent_tool_approval",
    "list_agent_tool_approvals",
    "append_agent_replay",
    "get_agent_replay",
]
