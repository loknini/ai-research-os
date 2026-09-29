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

    def read(self, n: int = -1):
        return self._payload[:n] if n is not None and n >= 0 else self._payload

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
check("全失败汇总每个检索源的真实原因", "duckduckgo: down" in out.get("error", "")
      and "wikipedia: down" in out.get("error", "")
      and "wikipedia 无可用结果" not in out.get("error", ""))

# ---------- 8. 非法 freshness ----------
with patch.object(ws.urllib.request, "urlopen", _urlopen_router([("duckduckgo", DDG_HTML)])):
    out = _run({"query": "hello", "freshness": "decade"})
check("非法 freshness 忽略并记 warnings", out.get("success") is True
      and any("freshness" in w for w in out.get("warnings", [])))

# ---------- 9. 预算断言 ----------
total = sum(ws.TIMEOUTS[p] for p in ("duckduckgo", "bocha", "wikipedia"))
check(f"搜索超时预算 {total}s 远低于技能 timeout(30s)", total <= 25)
skill_md = (ROOT / "backend" / "skills" / "web-search" / "SKILL.md").read_text(encoding="utf-8")
check("SKILL timeout 仍为 30", "timeout: 30" in skill_md)

# ---------- 10. SSRF 守卫 ----------
def _public_dns(host, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def _mixed_dns(host, *args, **kwargs):
    """字面 IP 按字面返回（还原真实解析行为），域名一律给公网 IP。"""
    import ipaddress

    try:
        ipaddress.ip_address(host)
        return [(socket.AF_INET6 if ":" in host else socket.AF_INET,
                 socket.SOCK_STREAM, 6, "", (host, 0))]
    except ValueError:
        return _public_dns(host)


def _private_dns(host, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]


with patch.object(ws.socket, "getaddrinfo", _public_dns):
    try:
        ws._assert_fetchable_url("https://example.com/a")
        check("公网 URL 放行", True)
    except Exception:
        check("公网 URL 放行", False)

for bad in ["http://127.0.0.1/x", "http://10.0.0.5/x", "http://169.254.169.254/",
            "http://[::1]/", "file:///etc/passwd", "ftp://a/b",
            "http://user:pw@example.com/"]:
    with patch.object(ws.socket, "getaddrinfo", _mixed_dns):
        try:
            ws._assert_fetchable_url(bad)
            check(f"拦截 {bad}", False)
        except Exception:
            check(f"拦截 {bad}", True)

with patch.object(ws.socket, "getaddrinfo", _private_dns):
    try:
        ws._assert_fetchable_url("http://example.com/")
        check("DNS 指向内网被拦截", False)
    except Exception:
        check("DNS 指向内网被拦截", True)

# ---------- 11. 重定向超限 ----------
guard = ws._FetchRedirectGuard()
with patch.object(ws.socket, "getaddrinfo", _public_dns):
    import urllib.request as _urlreq

    ok = False
    try:
        for i in range(4):
            guard.redirect_request(
                _urlreq.Request("https://example.com/0"), None, 302, "m",
                {"Location": f"https://example.com/{i + 1}"}, f"https://example.com/{i + 1}")
    except Exception:
        ok = guard.count == 4
    check("重定向超 3 跳终止", ok)

# ---------- 12. fetch 成功形状 ----------
FETCH_HTML = (
    "<html><head><style>x</style></head><body><h1>Hi</h1>"
    '<a href="/b">Bee</a><script>evil()</script><p>Body text here.</p></body></html>'
).encode()


class _FakeOpenerResp(_Resp):
    def __init__(self, payload, final_url):
        super().__init__(payload)
        self._final = final_url

    def geturl(self):
        return self._final


class _FakeOpener:
    def open(self, req, timeout=None):
        return _FakeOpenerResp(FETCH_HTML, "https://example.com/a")


with patch.object(ws.socket, "getaddrinfo", _public_dns):
    with patch.object(ws.urllib.request, "build_opener", lambda *a: _FakeOpener()):
        out = _run({"url": "https://example.com/a"})
check("fetch 成功", out.get("success") is True and out.get("mode") == "fetch")
check("fetch 去标签且去脚本", "evil()" not in out.get("content", "") and "Body text" in out.get("content", ""))
check("fetch 出站链接 ≤20", isinstance(out.get("links"), list)
      and out["links"] and out["links"][0]["url"] == "https://example.com/b")
check("薄页记 uncertainty", any("JS" in u for u in out.get("uncertainty", [])))

# ---------- 13. 200KB 截断 ----------
big = b"a" * (300 * 1024)


class _BigOpener:
    def open(self, req, timeout=None):
        return _FakeOpenerResp(big, "https://example.com/big")


with patch.object(ws.socket, "getaddrinfo", _public_dns):
    with patch.object(ws.urllib.request, "build_opener", lambda *a: _BigOpener()):
        out = _run({"url": "https://example.com/big"})
check("超 200KB 截断", out.get("success") is True
      and len(out.get("content", "").encode()) <= 200 * 1024)
check("截断记 warnings", any("200KB" in w for w in out.get("warnings", [])))

# ---------- 14. 无 query 无 url ----------
out = _run({"max_results": 3})
check("无 query 无 url 报错", out.get("success") is False)

print(f"\nTOTAL: {PASS + FAIL}  PASS: {PASS}  FAIL: {FAIL}")
sys.exit(1 if FAIL else 0)
