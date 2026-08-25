"""Verify the chat "regenerate / edit latest prompt" backend support.

Covers the two new conversation-message endpoints used by the Chat Hub MVP:
  * PUT  /api/conversations/{id}/messages/{message_id}            -> update content
  * POST /api/conversations/{id}/messages/delete-after            -> trim tail after an anchor

Scenarios:
  1. delete-after on the last user message removes only the trailing assistant reply.
  2. update changes the user message content (persisted).
  3. space isolation: another space cannot read/update the messages.
  4. delete-after on the first user message truncates the whole tail.
"""
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# isolated temp data dir so the user's real DB is untouched
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="airos_regen_")
os.environ.setdefault("PYTHONUTF8", "1")

from fastapi.testclient import TestClient  # type: ignore
from backend.server.main import app

SPACE = "qa_space"
HEADERS = {"X-Space-Key": SPACE}
OTHER = {"X-Space-Key": "other_space"}
CONV_ID = "conv_regen_01"

# 严格交替 user/assistant，时间戳递增（delete-after 依赖 timestamp 顺序）
SEED = [
    ("u1", "user", "你好", 1),
    ("a1", "assistant", "你好！有什么可以帮", 2),
    ("u2", "user", "讲讲 transformer", 3),
    ("a2", "assistant", "Transformer 是...", 4),
]


def seed(client):
    c = client.post("/api/conversations", headers=HEADERS, json={"id": CONV_ID, "title": "t", "messages": []})
    assert c.status_code == 200, c.text
    for mid, role, content, ts in SEED:
        r = client.post(
            f"/api/conversations/{CONV_ID}/messages",
            headers=HEADERS,
            json={"id": mid, "role": role, "content": content, "timestamp": ts},
        )
        assert r.status_code == 200, r.text


def get_ids(client):
    return [m["id"] for m in client.get(f"/api/conversations/{CONV_ID}/messages", headers=HEADERS).json()["messages"]]


def get_contents(client):
    return {m["id"]: m["content"] for m in client.get(f"/api/conversations/{CONV_ID}/messages", headers=HEADERS).json()["messages"]}


def main():
    with TestClient(app) as client:
        seed(client)

        # 1) delete-after u2 (ts=3) 应只删掉 a2，保留 u1/a1/u2
        d = client.post(f"/api/conversations/{CONV_ID}/messages/delete-after", headers=HEADERS, json={"messageId": "u2"})
        assert d.json()["success"] is True, d.text
        assert get_ids(client) == ["u1", "a1", "u2"], get_ids(client)
        print("[1] delete-after tail -> OK, remaining:", get_ids(client))

        # 2) update u2 content
        u = client.put(f"/api/conversations/{CONV_ID}/messages/u2", headers=HEADERS, json={"content": "讲讲 CNN"})
        assert u.json()["success"] is True, u.text
        assert get_contents(client)["u2"] == "讲讲 CNN", get_contents(client)
        print("[2] update content -> OK, u2 =", get_contents(client)["u2"])

        # 3) 空间隔离：另一个空间无法改写 u2
        client.put(f"/api/conversations/{CONV_ID}/messages/u2", headers=OTHER, json={"content": "HACKED"})
        assert get_contents(client)["u2"] == "讲讲 CNN", "space isolation broken: " + get_contents(client)["u2"]
        print("[3] space isolation -> OK (other space cannot mutate)")

        # 4) delete-after u1 (ts=1) 截断整条尾部，仅留 u1
        d2 = client.post(f"/api/conversations/{CONV_ID}/messages/delete-after", headers=HEADERS, json={"messageId": "u1"})
        assert d2.json()["success"] is True, d2.text
        assert get_ids(client) == ["u1"], get_ids(client)
        print("[4] delete-after head -> OK, remaining:", get_ids(client))

    print("RESULT: ALL_PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
