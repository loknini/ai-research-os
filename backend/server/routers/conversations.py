"""Conversation Hub CRUD routes -> in-process ``scripts/database.py``.

Every handler resolves ``space_id`` via ``Depends(get_space_id)`` and passes it
through to the DB layer for soft isolation.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import db
from ..deps import get_space_id
from ..errors import APIError

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    id: Optional[str] = None  # 允许前端自带 ID（与消息接口一致），缺省时后端生成 uuid4
    title: str = "新对话"
    messages: List[Dict[str, Any]] = []


class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    updatedAt: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None  # 会话级配置（如 RAG 接地开关 / 来源筛选）


class ChatMessageCreate(BaseModel):
    id: Optional[str] = None
    role: str
    content: Any = ""  # 支持纯文本字符串或多模态 content 数组（文本+图片）
    timestamp: Optional[int] = None
    metadata: Dict[str, Any] = {}
    conversationId: Optional[str] = None
    parentId: Optional[str] = None  # 父消息 id，用于分叉树


class ChatMessageUpdate(BaseModel):
    content: Any = ""  # 编辑提问时可能含多模态 content（文本+图片）


class DeleteAfterRequest(BaseModel):
    messageId: str


@router.get("")
async def list_conversations(space_id: str = Depends(get_space_id)):
    try:
        conversations = await db.database.get_all_conversations(space_id=space_id)
        return {"success": True, "conversations": conversations}
    except Exception as exc:
        raise APIError(str(exc), code="LIST_CONVERSATIONS_FAILED")


@router.post("")
async def create_conversation(req: ConversationCreate, space_id: str = Depends(get_space_id)):
    try:
        now = int(time.time() * 1000)
        conversation = {
            # 优先使用前端传入的 ID，保证前后端 ID 一致（否则前端后续 GET 会 404）
            "id": req.id or str(uuid.uuid4()),
            "title": req.title,
            "createdAt": now,
            "updatedAt": now,
            "messages": req.messages,
        }
        if not await db.database.insert_conversation(conversation, space_id=space_id):
            raise APIError("插入对话失败", code="INSERT_FAILED")
        return {"success": True, "conversation": await db.database.get_conversation_by_id(conversation["id"], space_id=space_id)}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="CREATE_CONVERSATION_FAILED")


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str, space_id: str = Depends(get_space_id)):
    try:
        conversation = await db.database.get_conversation_by_id(conversation_id, space_id=space_id)
        if not conversation:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "NOT_FOUND", "message": "Conversation not found"},
            )
        return {"success": True, "conversation": conversation}
    except Exception as exc:
        raise APIError(str(exc), code="GET_CONVERSATION_FAILED")


@router.put("/{conversation_id}")
async def update_conversation(conversation_id: str, req: ConversationUpdate, space_id: str = Depends(get_space_id)):
    try:
        updates = {k: v for k, v in req.model_dump(exclude_none=True).items()}
        if not await db.database.update_conversation(conversation_id, updates, space_id=space_id):
            raise APIError("更新对话失败", code="UPDATE_FAILED")
        return {"success": True, "conversation": await db.database.get_conversation_by_id(conversation_id, space_id=space_id)}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="UPDATE_CONVERSATION_FAILED")


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, space_id: str = Depends(get_space_id)):
    try:
        ok = await db.database.delete_conversation(conversation_id, space_id=space_id)
        return {"success": ok, "deleted": ok}
    except Exception as exc:
        raise APIError(str(exc), code="DELETE_CONVERSATION_FAILED")


@router.get("/{conversation_id}/messages")
async def get_messages(conversation_id: str, space_id: str = Depends(get_space_id)):
    try:
        messages = await db.database.get_conversation_messages(conversation_id, space_id=space_id)
        return {"success": True, "messages": messages}
    except Exception as exc:
        raise APIError(str(exc), code="GET_MESSAGES_FAILED")


@router.post("/{conversation_id}/messages/delete-after")
async def delete_messages_after(conversation_id: str, req: DeleteAfterRequest, space_id: str = Depends(get_space_id)):
    """删除锚点消息之后的所有消息（尾部截断）。

    锚点取最后一条 user 消息，从而删掉其后（即刚生成的）assistant 回复，
    配合「重新生成 / 编辑最新提问」使用。按空间隔离，幂等。
    """
    try:
        ok = await db.database.delete_chat_messages_after(req.messageId, space_id=space_id)
        return {"success": ok}
    except Exception as exc:
        raise APIError(str(exc), code="DELETE_MESSAGES_AFTER_FAILED")


@router.put("/{conversation_id}/messages/{message_id}")
async def update_message(conversation_id: str, message_id: str, req: ChatMessageUpdate, space_id: str = Depends(get_space_id)):
    """更新单条消息内容（用于「编辑最新提问」改写 user 消息正文）。"""
    try:
        ok = await db.database.update_chat_message(message_id, {"content": req.content}, space_id=space_id)
        if not ok:
            raise APIError("更新消息失败", code="UPDATE_FAILED")
        return {"success": True}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="UPDATE_MESSAGE_FAILED")


@router.post("/{conversation_id}/messages")
async def add_message(conversation_id: str, req: ChatMessageCreate, space_id: str = Depends(get_space_id)):
    try:
        now = int(time.time() * 1000)
        message = {
            "id": req.id or str(uuid.uuid4()),
            "conversationId": conversation_id,
            "role": req.role,
            "content": req.content,
            "timestamp": req.timestamp or now,
            "metadata": req.metadata,
            "parentId": req.parentId,
        }
        if not await db.database.insert_chat_message(message, space_id=space_id):
            raise APIError("插入消息失败", code="INSERT_FAILED")
        return {"success": True, "message": message}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="ADD_MESSAGE_FAILED")


@router.post("/{conversation_id}/switch-branch/{message_id}")
async def switch_branch(conversation_id: str, message_id: str, space_id: str = Depends(get_space_id)):
    """切换到包含 message_id 的分支。

    message_id 可以是树中任意节点；后端沿子链向下找到最新叶子并设为 current_leaf_id。
    返回更新后的对话（含新分支的消息路径）。
    """
    try:
        leaf_id = await db.database.switch_to_message(conversation_id, message_id, space_id=space_id)
        if leaf_id is None:
            raise APIError("消息不存在或不属于该会话", code="NOT_FOUND")
        conversation = await db.database.get_conversation_by_id(conversation_id, space_id=space_id)
        return {"success": True, "conversation": conversation, "leafId": leaf_id}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(str(exc), code="SWITCH_BRANCH_FAILED")


__all__ = ["router"]
