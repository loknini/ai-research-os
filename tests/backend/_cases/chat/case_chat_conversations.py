#!/usr/bin/env python3
"""聊天会话 HTTP 契约回归：ID、一致性编辑、裁剪与分支树。

本脚本合并了原先三个重复构造临时数据库和 ``TestClient`` 的 QA：

* 前后端 conversation ID 一致，自动生成 ID 后仍可写入消息；
* 编辑消息与 delete-after 裁剪保持 currentLeafId 正确；
* parentId 分支、重新生成、分支切换和 sibling 元数据正确；
* 上述写入与读取均受 space-key 隔离。
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

_TEMP_DIR = Path(tempfile.mkdtemp(prefix="airos-chat-conversations-"))
atexit.register(shutil.rmtree, _TEMP_DIR, ignore_errors=True)
os.environ["DATA_DIR"] = str(_TEMP_DIR)
os.environ.setdefault("PYTHONUTF8", "1")

from fastapi.testclient import TestClient  # noqa: E402
from scripts import database  # noqa: E402

database.configure_paths(
    data_dir=_TEMP_DIR,
    db_path=_TEMP_DIR / "ai_research_os.db",
)

from backend.server.main import app  # noqa: E402


def _headers(space: str) -> dict[str, str]:
    return {"X-Space-Key": space}


def _create_conversation(
    client: TestClient,
    conversation_id: str,
    space: str,
    *,
    title: str = "QA 会话",
) -> dict[str, Any]:
    response = client.post(
        "/api/conversations",
        headers=_headers(space),
        json={"id": conversation_id, "title": title, "messages": []},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("success") is True, payload
    return payload["conversation"]


def _add_message(
    client: TestClient,
    conversation_id: str,
    space: str,
    message_id: str,
    role: str,
    content: str,
    timestamp: int,
    *,
    parent_id: str | None = None,
) -> None:
    response = client.post(
        f"/api/conversations/{conversation_id}/messages",
        headers=_headers(space),
        json={
            "id": message_id,
            "role": role,
            "content": content,
            "timestamp": timestamp,
            "parentId": parent_id,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json().get("success") is True, response.text


def _conversation(client: TestClient, conversation_id: str, space: str) -> dict[str, Any]:
    response = client.get(
        f"/api/conversations/{conversation_id}",
        headers=_headers(space),
    )
    assert response.status_code == 200, response.text
    return response.json()["conversation"]


def _messages(client: TestClient, conversation_id: str, space: str) -> list[dict[str, Any]]:
    response = client.get(
        f"/api/conversations/{conversation_id}/messages",
        headers=_headers(space),
    )
    assert response.status_code == 200, response.text
    return response.json()["messages"]


def verify_id_contract(client: TestClient) -> None:
    space = "qa-conversation-id"
    conversation_id = f"conv-client-{uuid.uuid4().hex[:8]}"
    created = _create_conversation(client, conversation_id, space, title="ID 契约")
    assert created["id"] == conversation_id

    user_id = f"u-{uuid.uuid4().hex[:8]}"
    assistant_id = f"a-{uuid.uuid4().hex[:8]}"
    _add_message(client, conversation_id, space, user_id, "user", "你好", 1)
    _add_message(
        client,
        conversation_id,
        space,
        assistant_id,
        "assistant",
        "回复",
        2,
        parent_id=user_id,
    )
    detail = _conversation(client, conversation_id, space)
    assert [item["id"] for item in detail["messages"]] == [user_id, assistant_id]
    assert detail["currentLeafId"] == assistant_id

    generated = client.post(
        "/api/conversations",
        headers=_headers(space),
        json={"title": "后端生成 ID", "messages": []},
    )
    assert generated.status_code == 200, generated.text
    generated_id = generated.json().get("conversation", {}).get("id")
    assert generated_id
    response = client.post(
        f"/api/conversations/{generated_id}/messages",
        headers=_headers(space),
        json={"role": "user", "content": "x", "parentId": None},
    )
    assert response.status_code == 200 and response.json().get("success") is True
    print("[PASS] 会话 ID 契约")


def verify_edit_and_trim(client: TestClient) -> None:
    space = "qa-chat-edit"
    other_space = "qa-chat-edit-other"
    conversation_id = "conv-edit-trim"
    _create_conversation(client, conversation_id, space, title="编辑与裁剪")
    for message_id, role, content, timestamp in (
        ("edit-u1", "user", "你好", 10),
        ("edit-a1", "assistant", "你好！", 20),
        ("edit-u2", "user", "讲讲 Transformer", 30),
        ("edit-a2", "assistant", "Transformer 是……", 40),
    ):
        _add_message(client, conversation_id, space, message_id, role, content, timestamp)

    trimmed = client.post(
        f"/api/conversations/{conversation_id}/messages/delete-after",
        headers=_headers(space),
        json={"messageId": "edit-u2"},
    )
    assert trimmed.json().get("success") is True, trimmed.text
    assert [item["id"] for item in _messages(client, conversation_id, space)] == [
        "edit-u1",
        "edit-a1",
        "edit-u2",
    ]
    assert _conversation(client, conversation_id, space)["currentLeafId"] == "edit-u2"

    updated = client.put(
        f"/api/conversations/{conversation_id}/messages/edit-u2",
        headers=_headers(space),
        json={"content": "讲讲 CNN"},
    )
    assert updated.json().get("success") is True, updated.text
    content_by_id = {
        item["id"]: item["content"]
        for item in _messages(client, conversation_id, space)
    }
    assert content_by_id["edit-u2"] == "讲讲 CNN"

    client.put(
        f"/api/conversations/{conversation_id}/messages/edit-u2",
        headers=_headers(other_space),
        json={"content": "HACKED"},
    )
    content_by_id = {
        item["id"]: item["content"]
        for item in _messages(client, conversation_id, space)
    }
    assert content_by_id["edit-u2"] == "讲讲 CNN"

    trimmed_to_head = client.post(
        f"/api/conversations/{conversation_id}/messages/delete-after",
        headers=_headers(space),
        json={"messageId": "edit-u1"},
    )
    assert trimmed_to_head.json().get("success") is True, trimmed_to_head.text
    assert [item["id"] for item in _messages(client, conversation_id, space)] == ["edit-u1"]
    assert _conversation(client, conversation_id, space)["currentLeafId"] == "edit-u1"
    print("[PASS] 消息编辑、裁剪与空间隔离")


def verify_branching(client: TestClient) -> None:
    space = "qa-chat-branch"
    other_space = "qa-chat-branch-other"
    conversation_id = "conv-branch-tree"
    _create_conversation(client, conversation_id, space, title="分支树")
    for message_id, role, content, timestamp in (
        ("branch-u1", "user", "hello", 100),
        ("branch-a1", "assistant", "hi", 200),
        ("branch-u2", "user", "explain transformers", 300),
        ("branch-a2", "assistant", "Transformers are...", 400),
    ):
        _add_message(client, conversation_id, space, message_id, role, content, timestamp)

    detail = _conversation(client, conversation_id, space)
    assert [item.get("parentId") for item in detail["messages"]] == [
        None,
        "branch-u1",
        "branch-a1",
        "branch-u2",
    ]
    assert detail["currentLeafId"] == "branch-a2"

    _add_message(
        client,
        conversation_id,
        space,
        "branch-a2b",
        "assistant",
        "Transformers are neural...",
        500,
        parent_id="branch-u2",
    )
    detail = _conversation(client, conversation_id, space)
    assert [item["id"] for item in detail["messages"]] == [
        "branch-u1",
        "branch-a1",
        "branch-u2",
        "branch-a2b",
    ]

    _add_message(
        client,
        conversation_id,
        space,
        "branch-u2b",
        "user",
        "explain CNN",
        600,
        parent_id="branch-a1",
    )
    _add_message(
        client,
        conversation_id,
        space,
        "branch-a2c",
        "assistant",
        "CNN is...",
        700,
        parent_id="branch-u2b",
    )
    assert [
        item["id"] for item in _conversation(client, conversation_id, space)["messages"]
    ] == ["branch-u1", "branch-a1", "branch-u2b", "branch-a2c"]

    for leaf_id, expected in (
        ("branch-a2", ["branch-u1", "branch-a1", "branch-u2", "branch-a2"]),
        ("branch-a2b", ["branch-u1", "branch-a1", "branch-u2", "branch-a2b"]),
    ):
        switched = client.post(
            f"/api/conversations/{conversation_id}/switch-branch/{leaf_id}",
            headers=_headers(space),
        )
        assert switched.status_code == 200 and switched.json().get("leafId") == leaf_id
        assert [
            item["id"] for item in _conversation(client, conversation_id, space)["messages"]
        ] == expected

    detail = _conversation(client, conversation_id, space)
    regenerated = next(item for item in detail["messages"] if item["id"] == "branch-a2b")
    assert regenerated["siblingCount"] == 2
    assert regenerated["siblingIndex"] == 1
    assert set(regenerated["siblingIds"]) == {"branch-a2", "branch-a2b"}

    denied = client.post(
        f"/api/conversations/{conversation_id}/switch-branch/branch-a2",
        headers=_headers(other_space),
    )
    assert denied.json().get("success") is False
    hidden = client.get(
        f"/api/conversations/{conversation_id}",
        headers=_headers(other_space),
    )
    assert hidden.status_code == 404
    print("[PASS] 会话分支树、切换与 sibling 元数据")


def main() -> None:
    with TestClient(app) as client:
        verify_id_contract(client)
        verify_edit_and_trim(client)
        verify_branching(client)
    print("CHAT_CONVERSATIONS_QA_PASS")


if __name__ == "__main__":
    main()
