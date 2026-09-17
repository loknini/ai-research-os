"""Chat persistence repository."""
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

def _coerce_json_field(raw: Any) -> Dict[str, Any]:
    """把 SQLite 存的 JSON 文本安全地还原为 dict；空 / 非法返回 {}。"""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


async def get_all_conversations(space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间所有对话列表"""
    async with get_db() as conn:
        rows = await _fetchall(
            conn, 'SELECT * FROM conversations WHERE space_id = ? ORDER BY updated_at DESC', (space_id,))
        return [
            {
                'id': row['id'],
                'title': row['title'],
                'currentLeafId': row['current_leaf_id'] if 'current_leaf_id' in row.keys() else None,
                'createdAt': row['created_at'],
                'updatedAt': row['updated_at'],
                'metadata': _coerce_json_field(row['metadata']) if 'metadata' in row.keys() else {},
            }
            for row in rows
        ]


def _encode_chat_content(content):
    """聊天消息 content 透明编码：list/dict -> JSON 字符串（便于存入 TEXT 列），
    str/None 原样返回。配合 _decode_chat_content 实现多模态消息持久化。"""
    if isinstance(content, (list, dict)):
        return json.dumps(content, ensure_ascii=False)
    return content


def _decode_chat_content(raw):
    """聊天消息 content 透明解码：以 [ 或 { 开头的字符串尝试解析为 JSON，
    失败则原样返回（兼容纯文本消息，且避免误判以 [ 开头的普通文本）。"""
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith(('[', '{')):
            try:
                return json.loads(s)
            except (ValueError, TypeError):
                return raw
    return raw


async def _row_to_message(m: aiosqlite.Row) -> Dict[str, Any]:
    """把 chat_messages 行转为前端可用的消息字典。"""
    return {
        'id': m['id'],
        'role': m['role'],
        'content': _decode_chat_content(m['content']),
        'timestamp': m['timestamp'],
        'metadata': json.loads(m['metadata']) if m['metadata'] else {},
        'parentId': m['parent_id'] if 'parent_id' in m.keys() else None,
    }


async def get_message_path(conn: aiosqlite.Connection, conversation_id: str, leaf_id: Optional[str], space_id: str) -> List[Dict[str, Any]]:
    """从 leaf_id 沿 parent_id 链向上遍历到根，返回正序消息列表（根 → 叶）。

    leaf_id 为 None 时返回空列表。同时为每条消息附加 siblingCount 和 siblingIndex，
    供前端渲染分支切换箭头。
    """
    if not leaf_id:
        return []
    chain: List[Dict[str, Any]] = []
    visited: set = set()
    cur_id: Optional[str] = leaf_id
    while cur_id and cur_id not in visited:
        visited.add(cur_id)
        row = await _fetchone(
            conn,
            "SELECT * FROM chat_messages WHERE id = ? AND conversation_id = ? AND space_id = ?",
            (cur_id, conversation_id, space_id),
        )
        if not row:
            break
        msg = await _row_to_message(row)
        chain.append(msg)
        cur_id = row["parent_id"]
    chain.reverse()

    # 为每条消息附加兄弟数信息（同一 parent_id 下的消息数）
    for msg in chain:
        parent_id = msg.get("parentId")
        if parent_id:
            sib_rows = await _fetchall(
                conn,
                "SELECT id FROM chat_messages WHERE conversation_id = ? AND space_id = ? AND parent_id = ? ORDER BY timestamp ASC",
                (conversation_id, space_id, parent_id),
            )
        else:
            sib_rows = await _fetchall(
                conn,
                "SELECT id FROM chat_messages WHERE conversation_id = ? AND space_id = ? AND parent_id IS NULL ORDER BY timestamp ASC",
                (conversation_id, space_id),
            )
        sibling_ids = [r["id"] for r in sib_rows]
        msg["siblingCount"] = len(sibling_ids)
        msg["siblingIndex"] = sibling_ids.index(msg["id"]) if msg["id"] in sibling_ids else 0
        msg["siblingIds"] = sibling_ids
    return chain


async def get_conversation_by_id(conversation_id: str, space_id: str = DEFAULT_SPACE) -> Optional[Dict[str, Any]]:
    """获取单个对话详情（含当前分支消息，均按空间过滤）。

    返回的 messages 是从根到 current_leaf_id 的路径；每条消息含 siblingCount /
    siblingIndex / siblingIds 供前端渲染分支切换。
    """
    async with get_db() as conn:
        row = await _fetchone(conn, 'SELECT * FROM conversations WHERE id = ? AND space_id = ?', (conversation_id, space_id))
        if not row:
            return None
        leaf_id = row['current_leaf_id'] if 'current_leaf_id' in row.keys() else None
        messages = await get_message_path(conn, conversation_id, leaf_id, space_id)
        return {
            'id': row['id'],
            'title': row['title'],
            'currentLeafId': leaf_id,
            'createdAt': row['created_at'],
            'updatedAt': row['updated_at'],
            'metadata': _coerce_json_field(row['metadata']) if 'metadata' in row.keys() else {},
            'messages': messages,
        }


async def insert_conversation(conversation: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """插入新对话（会话与消息均按空间打标；自动维护 current_leaf_id）。"""
    try:
        async with get_db() as conn:
            messages = conversation.get('messages', [])
            leaf_id = messages[-1]['id'] if messages else None
            await conn.execute(
                'INSERT INTO conversations (id, title, current_leaf_id, created_at, updated_at, metadata, space_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (conversation['id'], conversation.get('title', '新对话'), leaf_id,
                 conversation['createdAt'], conversation['updatedAt'],
                 json.dumps(conversation.get('metadata', {})), space_id))
            prev_id: Optional[str] = None
            for msg in messages:
                await conn.execute('''
                    INSERT INTO chat_messages (id, conversation_id, parent_id, role, content, timestamp, metadata, space_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    msg['id'], conversation['id'], prev_id, msg['role'], msg['content'],
                    msg['timestamp'], json.dumps(msg.get('metadata', {})), space_id))
                prev_id = msg['id']
            return True
    except Exception as e:
        print(f"Insert conversation error: {e}")
        return False


async def update_conversation(conversation_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新对话信息（按空间校验）"""
    try:
        async with get_db() as conn:
            rowcount = 0
            if 'title' in updates:
                cur = await conn.execute(
                    'UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND space_id = ?',
                    (updates['title'], int(datetime.now().timestamp() * 1000), conversation_id, space_id))
                rowcount += cur.rowcount
            if 'metadata' in updates:
                cur = await conn.execute(
                    'UPDATE conversations SET metadata = ?, updated_at = ? WHERE id = ? AND space_id = ?',
                    (json.dumps(updates['metadata']), int(datetime.now().timestamp() * 1000), conversation_id, space_id))
                rowcount += cur.rowcount
            if 'updatedAt' in updates:
                cur = await conn.execute(
                    'UPDATE conversations SET updated_at = ? WHERE id = ? AND space_id = ?',
                    (updates['updatedAt'], conversation_id, space_id))
                rowcount += cur.rowcount
            return rowcount > 0
    except Exception as e:
        print(f"Update conversation error: {e}")
        return False


async def delete_conversation(conversation_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除对话（关联消息随外键级联删除；严格限定本空间）"""
    try:
        async with get_db() as conn:
            cur = await conn.execute('DELETE FROM conversations WHERE id = ? AND space_id = ?', (conversation_id, space_id))
            return cur.rowcount > 0
    except Exception as e:
        print(f"Delete conversation error: {e}")
        return False


async def insert_chat_message(message: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """插入单条聊天消息（按空间打标；自动设置 parent_id 并更新 current_leaf_id）。

    message 可选传入 ``parentId`` 指定父消息；不传则尝试取会话当前 current_leaf_id。
    插入后把会话的 current_leaf_id 更新为本消息 id。
    """
    try:
        async with get_db() as conn:
            conv_id = message['conversationId']
            parent_id = message.get('parentId')
            if not parent_id:
                row = await _fetchone(
                    conn,
                    "SELECT current_leaf_id FROM conversations WHERE id = ? AND space_id = ?",
                    (conv_id, space_id),
                )
                if row:
                    parent_id = row["current_leaf_id"]
            await conn.execute('''
                INSERT INTO chat_messages (id, conversation_id, parent_id, role, content, timestamp, metadata, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                message['id'],
                conv_id,
                parent_id,
                message['role'],
                _encode_chat_content(message['content']),
                message['timestamp'],
                json.dumps(message.get('metadata', {})),
                space_id,
            ))
            now = int(time.time() * 1000)
            await conn.execute(
                "UPDATE conversations SET current_leaf_id = ?, updated_at = ? WHERE id = ? AND space_id = ?",
                (message['id'], now, conv_id, space_id),
            )
            return True
    except Exception as e:
        print(f"Insert chat message error: {e}")
        return False


async def update_chat_message(message_id: str, updates: Dict[str, Any], space_id: str = DEFAULT_SPACE) -> bool:
    """更新单条聊天消息（按空间校验，防误伤他人数据）。

    仅支持 ``content`` / ``timestamp`` 字段。用于「编辑最新提问」时改写 user 消息正文。
    """
    try:
        set_clauses: List[str] = []
        params: List[Any] = []
        if "content" in updates:
            set_clauses.append("content = ?")
            params.append(_encode_chat_content(updates["content"]))
        if "timestamp" in updates:
            set_clauses.append("timestamp = ?")
            params.append(updates["timestamp"])
        if not set_clauses:
            return True
        params.append(message_id)
        params.append(space_id)
        async with get_db() as conn:
            cur = await conn.execute(
                f"UPDATE chat_messages SET {', '.join(set_clauses)} WHERE id = ? AND space_id = ?",
                params,
            )
            return cur.rowcount > 0
    except Exception as e:
        print(f"Update chat message error: {e}")
        return False


async def delete_chat_messages_after(message_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """删除某条消息之后的所有消息（按 timestamp 顺序尾部截断，幂等）。

    用于「重新生成」与「编辑最新提问」：锚定最后一条 user 消息，删掉其后的
    assistant 回复。截断后必须把会话的 current_leaf_id 指回锚点，否则当前分支
    会继续指向已删除的叶子，随后读取消息路径时将得到空列表。
    """
    try:
        async with get_db() as conn:
            row = await _fetchone(
                conn,
                "SELECT timestamp, conversation_id FROM chat_messages WHERE id = ? AND space_id = ?",
                (message_id, space_id),
            )
            if row:
                now = int(time.time() * 1000)
                await conn.execute(
                    "DELETE FROM chat_messages WHERE conversation_id = ? AND space_id = ? AND timestamp > ?",
                    (row["conversation_id"], space_id, row["timestamp"]),
                )
                await conn.execute(
                    "UPDATE conversations SET current_leaf_id = ?, updated_at = ? WHERE id = ? AND space_id = ?",
                    (message_id, now, row["conversation_id"], space_id),
                )
            return True
    except Exception as e:
        print(f"Delete chat messages after error: {e}")
        return False


async def get_conversation_messages(conversation_id: str, space_id: str = DEFAULT_SPACE) -> List[Dict[str, Any]]:
    """获取某空间对话当前分支的消息（从根到 current_leaf_id）。"""
    async with get_db() as conn:
        row = await _fetchone(
            conn,
            "SELECT current_leaf_id FROM conversations WHERE id = ? AND space_id = ?",
            (conversation_id, space_id),
        )
        if not row:
            return []
        leaf_id = row["current_leaf_id"] if "current_leaf_id" in row.keys() else None
        return await get_message_path(conn, conversation_id, leaf_id, space_id)


async def switch_conversation_leaf(conversation_id: str, leaf_id: str, space_id: str = DEFAULT_SPACE) -> bool:
    """切换对话的当前分支到指定叶子消息（按空间校验）。

    用于前端「上一条/下一条分支」导航。leaf_id 必须属于该会话且在该空间内。
    """
    try:
        async with get_db() as conn:
            row = await _fetchone(
                conn,
                "SELECT id FROM chat_messages WHERE id = ? AND conversation_id = ? AND space_id = ?",
                (leaf_id, conversation_id, space_id),
            )
            if not row:
                return False
            now = int(time.time() * 1000)
            cur = await conn.execute(
                "UPDATE conversations SET current_leaf_id = ?, updated_at = ? WHERE id = ? AND space_id = ?",
                (leaf_id, now, conversation_id, space_id),
            )
            return cur.rowcount > 0
    except Exception as e:
        print(f"Switch conversation leaf error: {e}")
        return False


async def switch_to_message(conversation_id: str, message_id: str, space_id: str = DEFAULT_SPACE) -> Optional[str]:
    """切换分支到包含 message_id 的路径。

    message_id 可以是树中任意节点（不一定是叶子）。本函数沿子节点链向下走到
    最新叶子，然后把 current_leaf_id 设为该叶子并返回其 id。
    """
    try:
        async with get_db() as conn:
            # 确认消息存在且属于该会话/空间
            row = await _fetchone(
                conn,
                "SELECT id FROM chat_messages WHERE id = ? AND conversation_id = ? AND space_id = ?",
                (message_id, conversation_id, space_id),
            )
            if not row:
                return None
            # 向下找叶子：反复查 parent_id = 当前 id 的最新一条
            cur_id = message_id
            while True:
                child = await _fetchone(
                    conn,
                    "SELECT id FROM chat_messages WHERE conversation_id = ? AND space_id = ? AND parent_id = ? ORDER BY timestamp DESC LIMIT 1",
                    (conversation_id, space_id, cur_id),
                )
                if not child:
                    break
                cur_id = child["id"]
            now = int(time.time() * 1000)
            await conn.execute(
                "UPDATE conversations SET current_leaf_id = ?, updated_at = ? WHERE id = ? AND space_id = ?",
                (cur_id, now, conversation_id, space_id),
            )
            return cur_id
    except Exception as e:
        print(f"Switch to message error: {e}")
        return None


__all__ = [
    "_coerce_json_field",
    "get_all_conversations",
    "_encode_chat_content",
    "_decode_chat_content",
    "_row_to_message",
    "get_message_path",
    "get_conversation_by_id",
    "insert_conversation",
    "update_conversation",
    "delete_conversation",
    "insert_chat_message",
    "update_chat_message",
    "delete_chat_messages_after",
    "get_conversation_messages",
    "switch_conversation_leaf",
    "switch_to_message",
]
