#!/usr/bin/env python3
"""
QA 验证脚本：web_search 技能（输出契约 + 降级 + key 轮换 + 预算）

覆盖范围：
  1. 缺 query 参数 → success:false
  2. 输出形状：新老字段兼容（success/provider/query/results + engine/status/
     uncertainty/warnings/attempts）
  3. DuckDuckGo 成功：attempts 单条 ok:true（含 durationSeconds）
  4. DDG 异常 → 自动降级 wikipedia
  5. 超时类错误单次重试（warnings 含“重试”）
  6. Bocha 多 key 轮换：401 先换 key（记 keyIndex）再换引擎
  7. 全失败 → success:false + status:"unavailable" + attempts 非空
  8. 非法 freshness 被忽略并记 warnings
  9. 超时预算断言：各源超时之和远低于技能 timeout（30s）

所有外部请求都通过 monkeypatch 注入（urllib.request.urlopen），
脚本不触网、不写库，可重复运行。
"""

import importlib.util
import io
import json
import os
import socket
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
MOD_PATH = ROOT / "backend" / "skills" / "web-search" / "scripts" / "web_search.py"

_spec = importlib.util.spec_from_file_location("web_search_skill", MOD_PATH)
assert _spec and _spec.loader
ws = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws)

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name}")


class _Resp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _run(params, env=None):
    """以给定 stdin 参数与环境变量跑 main()，返回 stdout JSON。"""
    base_env = {"WEB_SEARCH_PROVIDER": "", "BOCHA_API_KEY": ""}
    if env:
        base_env.update(env)
    with patch.dict(os.environ, base_env, clear=False):
        with patch.object(ws.sys, "stdin", io.StringIO(json.dumps(params))):
            buf = io.StringIO()
            with patch.object(ws.sys, "stdout", buf):
                ws.main()
    return json.loads(buf.getvalue())


DDG_HTML = (
    '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">Title A</a>'
    '<a class="result__snippet" href="x">Snippet A</a>'
).encode()

WIKI_JSON = json.dumps(
    {"query": {"search": [{"title": "T", "snippet": "S"}]}}
).encode()

BOCHA_JSON = json.dumps(
    {"data": {"webPages": {"value": [
        {"name": "B", "url": "https://b.example", "summary": "BS",
         "dateLastCrawled": "2026-01-01"},
    ]}}}
).encode()


def _urlopen_router(routes):
    """按 URL 关键字分发假响应；routes: [(keyword, bytes|Exception), ...]。"""
    calls = []

    def fake(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        calls.append(url)
        for keyword, payload in routes:
            if keyword in url:
                if isinstance(payload, Exception):
                    raise payload
                return _Resp(payload)
        raise AssertionError(f"unexpected url: {url}")

    fake.calls = calls
    return fake


# ---------- 1. 缺 query ----------
out = _run({})
check("缺 query 返回 success:false", out.get("success") is False)

# ---------- 2/3. DDG 成功 + 形状 ----------
with patch.object(ws.urllib.request, "urlopen", _urlopen_router([("duckduckgo", DDG_HTML)])):
    out = _run({"query": "hello", "max_results": 1})
check("DDG 成功", out.get("success") is True)
check("provider/engine/status 兼容", out.get("provider") == "duckduckgo"
      and out.get("engine") == "duckduckgo" and out.get("status") == "ok")
check("results 结构", isinstance(out.get("results"), list) and out["results"]
      and out["results"][0]["url"] == "https://example.com/a")
check("uncertainty/warnings/attempts 存在", isinstance(out.get("uncertainty"), list)
      and isinstance(out.get("warnings"), list) and isinstance(out.get("attempts"), list))
check("attempt 单条 ok:true 含耗时", len(out["attempts"]) == 1 and out["attempts"][0]["ok"] is True
      and isinstance(out["attempts"][0].get("durationSeconds"), (int, float)))

# ---------- 4. DDG 异常 → wikipedia ----------
router = _urlopen_router([
    ("duckduckgo", urllib.error.URLError("boom")),
    ("wikipedia", WIKI_JSON),
])
with patch.object(ws.urllib.request, "urlopen", router):
    out = _run({"query": "hello"})
check("DDG 异常降级 wikipedia", out.get("success") is True and out.get("provider") == "wikipedia")
check("降级 attempts 记录两源", [a["provider"] for a in out["attempts"]] == ["duckduckgo", "wikipedia"])

# ---------- 5. 超时重试 ----------
router = _urlopen_router([
    ("duckduckgo", DDG_HTML),
])
calls = {"n": 0}
orig = router

def flaky(req, timeout=None):
    calls["n"] += 1
    if calls["n"] == 1:
        raise urllib.error.URLError(socket.timeout("timed out"))
    return orig(req, timeout)

with patch.object(ws.urllib.request, "urlopen", flaky):
    out = _run({"query": "hello"})
check("超时重试后成功", out.get("success") is True)
check("重试记 warnings", any("重试" in w for w in out.get("warnings", [])))
check("重试记两次 attempts", len([a for a in out["attempts"] if a["provider"] == "duckduckgo"]) == 2)

# ---------- 6. Bocha 多 key 轮换 ----------
err401 = urllib.error.HTTPError("https://api.bochaai.com/v1/web-search", 401, "unauth", {}, None)
seen_auth = {}


def bocha_router(req, timeout=None):
    auth = req.get_header("Authorization")
    if auth not in seen_auth:
        seen_auth[auth] = True
        if auth == "Bearer k1":
            raise err401
    return _Resp(BOCHA_JSON)


with patch.object(ws.urllib.request, "urlopen", bocha_router):
    out = _run({"query": "hello"}, env={"WEB_SEARCH_PROVIDER": "bocha", "BOCHA_API_KEY": "k1,k2"})
check("多 key 轮换后成功", out.get("success") is True and out.get("provider") == "bocha")
atts = [a for a in out.get("attempts", []) if a["provider"] == "bocha"]
check("attempts 记 keyIndex", [a.get("keyIndex") for a in atts] == [0, 1]
      and atts[0]["ok"] is False and atts[1]["ok"] is True)
check("轮换记 warnings", any("轮换" in w for w in out.get("warnings", [])))

# ---------- 7. 全失败 ----------
def always_fail(req, timeout=None):
    raise urllib.error.URLError("down")


with patch.object(ws.urllib.request, "urlopen", always_fail):
    out = _run({"query": "hello"})
check("全失败 success:false", out.get("success") is False)
check("全失败 status unavailable", out.get("status") == "unavailable")
check("全失败 attempts 非空且有 error", len(out.get("attempts", [])) >= 2
      and all("error" in a for a in out["attempts"] if not a["ok"]))

# ---------- 8. 非法 freshness ----------
with patch.object(ws.urllib.request, "urlopen", _urlopen_router([("duckduckgo", DDG_HTML)])):
    out = _run({"query": "hello", "freshness": "decade"})
check("非法 freshness 忽略并记 warnings", out.get("success") is True
      and any("freshness" in w for w in out.get("warnings", [])))

# ---------- 9. 预算断言 ----------
total = sum(ws.TIMEOUTS.values())
check(f"超时预算 {total}s 远低于技能 timeout(30s)", total <= 25)
skill_md = (ROOT / "backend" / "skills" / "web-search" / "SKILL.md").read_text(encoding="utf-8")
check("SKILL timeout 仍为 30", "timeout: 30" in skill_md)

print(f"\nTOTAL: {PASS + FAIL}  PASS: {PASS}  FAIL: {FAIL}")
sys.exit(1 if FAIL else 0)
