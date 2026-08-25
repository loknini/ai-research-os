"""QA: 验证「新建/清空对话后前端与后端 conversation ID 一致」，根治 add_message 500 / 空白框。

复现 Task #27 根因：此前 createConversationAPI 仅返回 boolean、前端用本地生成 id，
而后端曾忽略/重新生成 UUID，导致前端后续 add_message 时 conversation 不存在 → 500 → 空白框。

本脚本用真实 TestClient 驱动 HTTP 层（含 get_space_id 依赖），验证：
  A. 前端自带 id 时，后端 create_conversation 返回相同 id（前后端 ID 一致）；
  B. 据此 id 调 add_message 成功（不 500）；
  C. 前端不带 id 时，后端生成 id，据此 id 调 add_message 同样成功。

隔离临时 DATA_DIR，不污染真实 data/。
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="qa_convid_"))
os.environ["DATA_DIR"] = str(TMP)  # 必须在 import app 之前设置

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from scripts import database  # noqa: E402
database.DB_PATH = TMP / "ai_research_os.db"  # noqa: E402
from backend.server.main import app  # noqa: E402

SPACE = "qa-dream"
HEADERS = {"X-Space-Key": SPACE}

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


print("== A. 前端自带 id：后端应原样返回该 id ==")
with TestClient(app) as client:
    conv_id = f"conv-client-{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/api/conversations",
        headers=HEADERS,
        json={"id": conv_id, "title": "A-测试", "messages": []},
    )
    data = r.json()
    check("create 返回 success", data.get("success") is True, r.text)
    returned = data.get("conversation", {}).get("id")
    check("返回 id == 前端传入 id", returned == conv_id, f"returned={returned} expected={conv_id}")

    print("== B. 用该 id 插入消息（旧 bug 会 500）==")
    um = f"u-{uuid.uuid4().hex[:8]}"
    r2 = client.post(
        f"/api/conversations/{conv_id}/messages",
        headers=HEADERS,
        json={"id": um, "role": "user", "content": "你好", "parentId": None},
    )
    check("user 消息插入成功", r2.json().get("success") is True, r2.text)

    am = f"a-{uuid.uuid4().hex[:8]}"
    r3 = client.post(
        f"/api/conversations/{conv_id}/messages",
        headers=HEADERS,
        json={"id": am, "role": "assistant", "content": "回复", "parentId": um},
    )
    check("assistant 消息插入成功(无500)", r3.json().get("success") is True, r3.text)

    # 详情应返回 root->leaf 路径 [user, assistant]
    r4 = client.get(f"/api/conversations/{conv_id}", headers=HEADERS)
    msgs = r4.json().get("conversation", {}).get("messages", [])
    check("详情含 2 条消息(user+assistant)", len(msgs) == 2, f"len={len(msgs)}")
    check("current_leaf 指向 assistant", msgs[-1]["id"] == am, f"leaf={msgs[-1]['id']}")

    print("== C. 前端不带 id：后端生成 id，据此插入消息成功 ==")
    r5 = client.post(
        "/api/conversations",
        headers=HEADERS,
        json={"title": "C-测试", "messages": []},
    )
    cid2 = r5.json().get("conversation", {}).get("id")
    check("后端生成了 id", bool(cid2) and cid2 != "", f"cid2={cid2}")
    r6 = client.post(
        f"/api/conversations/{cid2}/messages",
        headers=HEADERS,
        json={"role": "user", "content": "x", "parentId": None},
    )
    check("无自带 id 时消息插入成功", r6.json().get("success") is True, r6.text)

print(f"\n结果: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
