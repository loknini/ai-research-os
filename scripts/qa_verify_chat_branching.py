"""Verify chat branching tree: parent_id, current_leaf_id, branch switch.

Scenarios:
  1. Seed conversation: parent_id chain auto-built, current_leaf_id = last message.
  2. Regenerate: new assistant sibling (same parentId), current_leaf_id switches.
  3. Edit: new user sibling (same parentId) + new assistant child, current_leaf_id switches.
  4. Branch switch: navigate back to old branch, path changes correctly.
  5. Sibling info: siblingCount / siblingIndex / siblingIds populated.
  6. Space isolation: other space cannot switch branch or see messages.
"""
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="airos_branch_")
os.environ.setdefault("PYTHONUTF8", "1")

from fastapi.testclient import TestClient  # type: ignore
from backend.server.main import app

SPACE = "qa_branch"
HEADERS = {"X-Space-Key": SPACE}
OTHER = {"X-Space-Key": "other"}
CONV_ID = "conv_branch_01"


def seed(client):
    """Create a conversation with u1 -> a1 -> u2 -> a2."""
    r = client.post("/api/conversations", headers=HEADERS, json={"id": CONV_ID, "title": "branch test", "messages": []})
    assert r.status_code == 200, r.text
    for mid, role, content, ts in [
        ("u1", "user", "hello", 100),
        ("a1", "assistant", "hi there", 200),
        ("u2", "user", "explain transformers", 300),
        ("a2", "assistant", "Transformers are...", 400),
    ]:
        r = client.post(
            f"/api/conversations/{CONV_ID}/messages",
            headers=HEADERS,
            json={"id": mid, "role": role, "content": content, "timestamp": ts},
        )
        assert r.status_code == 200, r.text


def get_conv(client, space=SPACE):
    hdrs = {"X-Space-Key": space}
    r = client.get(f"/api/conversations/{CONV_ID}", headers=hdrs)
    assert r.status_code == 200, r.text
    return r.json()["conversation"]


def get_msg_ids(client, space=SPACE):
    return [m["id"] for m in get_conv(client, space)["messages"]]


def main():
    with TestClient(app) as client:
        seed(client)

        # 1) Verify parent_id chain and current_leaf_id
        conv = get_conv(client)
        msgs = conv["messages"]
        assert len(msgs) == 4, f"expected 4 msgs, got {len(msgs)}"
        assert msgs[0]["id"] == "u1" and msgs[0]["parentId"] is None, msgs[0]
        assert msgs[1]["id"] == "a1" and msgs[1]["parentId"] == "u1", msgs[1]
        assert msgs[2]["id"] == "u2" and msgs[2]["parentId"] == "a1", msgs[2]
        assert msgs[3]["id"] == "a2" and msgs[3]["parentId"] == "u2", msgs[3]
        assert conv["currentLeafId"] == "a2", conv["currentLeafId"]
        print("[1] parent_id chain + currentLeafId -> OK")

        # 2) Regenerate a2: create new assistant with parentId=u2 (sibling of a2)
        r = client.post(
            f"/api/conversations/{CONV_ID}/messages",
            headers=HEADERS,
            json={"id": "a2b", "role": "assistant", "content": "Transformers are neural...", "timestamp": 500, "parentId": "u2"},
        )
        assert r.status_code == 200, r.text
        conv = get_conv(client)
        assert conv["currentLeafId"] == "a2b", f"expected a2b, got {conv['currentLeafId']}"
        msg_ids = [m["id"] for m in conv["messages"]]
        assert msg_ids == ["u1", "a1", "u2", "a2b"], msg_ids
        # a2 should NOT be in the current path, but should still exist in DB
        # (verify via switch-branch back to a2)
        print("[2] regenerate creates sibling -> OK, path:", msg_ids)

        # 3) Edit u2: create new user with parentId=a1 (sibling of u2), then new assistant
        r = client.post(
            f"/api/conversations/{CONV_ID}/messages",
            headers=HEADERS,
            json={"id": "u2b", "role": "user", "content": "explain CNN", "timestamp": 600, "parentId": "a1"},
        )
        assert r.status_code == 200, r.text
        r = client.post(
            f"/api/conversations/{CONV_ID}/messages",
            headers=HEADERS,
            json={"id": "a2c", "role": "assistant", "content": "CNN is...", "timestamp": 700, "parentId": "u2b"},
        )
        assert r.status_code == 200, r.text
        conv = get_conv(client)
        assert conv["currentLeafId"] == "a2c", f"expected a2c, got {conv['currentLeafId']}"
        msg_ids = [m["id"] for m in conv["messages"]]
        assert msg_ids == ["u1", "a1", "u2b", "a2c"], msg_ids
        print("[3] edit creates new branch -> OK, path:", msg_ids)

        # 4) Switch back to original branch (a2)
        r = client.post(f"/api/conversations/{CONV_ID}/switch-branch/a2", headers=HEADERS)
        assert r.status_code == 200, r.text
        assert r.json()["leafId"] == "a2", r.json()
        conv = get_conv(client)
        msg_ids = [m["id"] for m in conv["messages"]]
        assert msg_ids == ["u1", "a1", "u2", "a2"], msg_ids
        print("[4] switch to original branch -> OK, path:", msg_ids)

        # Switch to a2b (regenerated branch)
        r = client.post(f"/api/conversations/{CONV_ID}/switch-branch/a2b", headers=HEADERS)
        assert r.status_code == 200, r.text
        conv = get_conv(client)
        msg_ids = [m["id"] for m in conv["messages"]]
        assert msg_ids == ["u1", "a1", "u2", "a2b"], msg_ids
        print("[4b] switch to regenerated branch -> OK, path:", msg_ids)

        # 5) Sibling info: at the a2/a2b level, siblingCount should be 2
        conv = get_conv(client)
        a2b_msg = next(m for m in conv["messages"] if m["id"] == "a2b")
        assert a2b_msg["siblingCount"] == 2, f"expected 2 siblings, got {a2b_msg['siblingCount']}"
        assert a2b_msg["siblingIndex"] == 1, f"expected index 1, got {a2b_msg['siblingIndex']}"
        assert set(a2b_msg["siblingIds"]) == {"a2", "a2b"}, a2b_msg["siblingIds"]
        # u1 and a1 should have siblingCount == 1
        u1_msg = next(m for m in conv["messages"] if m["id"] == "u1")
        assert u1_msg["siblingCount"] == 1, u1_msg
        print("[5] sibling info -> OK, a2b: count=2, index=1, ids=", a2b_msg["siblingIds"])

        # 6) Space isolation: other space cannot switch branch
        r = client.post(f"/api/conversations/{CONV_ID}/switch-branch/a2", headers=OTHER)
        assert r.json()["success"] is False, r.json()
        # Other space cannot see the conversation at all
        r = client.get(f"/api/conversations/{CONV_ID}", headers=OTHER)
        assert r.status_code == 404, r.text
        print("[6] space isolation -> OK (other space cannot switch or read)")

    print("RESULT: ALL_PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
