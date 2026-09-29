#!/usr/bin/env python3
"""RAG 子系统独立验证脚本（隔离 DATA_DIR，打桩 LLM/嵌入）。

覆盖：
  * 文件发现（多路径 / 递归 / 类型过滤）
  * 索引编排（向量模式 + 关键词降级）
  * 切片落库与向量写入
  * 检索 + 带引用回答（向量 / 关键词双路）
  * 源 CRUD 与级联删除
运行：python -m scripts.qa_verify_rag
"""
from __future__ import annotations

import asyncio
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

TMP = Path(tempfile.mkdtemp(prefix="rag_qa_"))

import scripts.database as database  # noqa: E402

# 隔离数据库到临时目录（覆盖模块级全局）。
database.configure_paths(data_dir=TMP, db_path=TMP / "qa_rag.db")
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

from backend.server.rag import service as rag_service  # noqa: E402
from backend.server.llm import llm_client  # noqa: E402

# 让 llm_client 视为「已配置」，并打桩嵌入 / 对话。
llm_client.settings.llm_api_key = "test"
llm_client.settings.llm_base_url = "http://localhost/v1"
llm_client.settings.llm_model = "test-model"


def fake_embed(texts, model=None):
    return [[float(len(t)), float(t.count("a")), float(t.count("e")), float(len(set(t)))]
            for t in texts]


def fake_call_llm(messages, **kw):
    return "测试回答，引用见 [1]。"


llm_client.embed = fake_embed
llm_client.call_llm = fake_call_llm

SPACE = "qa_space"


def make_corpus() -> Path:
    corpus = TMP / "corpus"
    (corpus / "sub").mkdir(parents=True, exist_ok=True)
    (corpus / "a.txt").write_text(
        "人工智能是计算机科学的一个分支。深度学习推动了自然语言处理的进步。", encoding="utf-8")
    (corpus / "sub" / "b.md").write_text(
        "# 标题\n\nRAG 检索增强生成结合了检索与生成模型。向量数据库用于存储嵌入。", encoding="utf-8")
    (corpus / "ignore.log").write_text("should be ignored", encoding="utf-8")
    return corpus


async def main() -> None:
    await database.init_db()
    corpus = make_corpus()

    # 1) 文件发现：递归 + 默认类型过滤应排除 .log
    files = rag_service.discover_files([str(corpus)], True, None)
    names = sorted(f.name for f in files)
    assert "a.txt" in names and "b.md" in names and "ignore.log" not in names, f"discover 失败: {names}"
    print("PASS discover_files:", names)

    # 2) 索引（向量模式）—— 仿照路由：先建源，再索引（嵌入一律走全局配置）
    await database.create_rag_source("src-vec", SPACE, "src-vec", [str(corpus)], True,
                                     ["pdf", "txt", "md"], status="indexing")
    res = await rag_service.index_source("src-vec", SPACE, [str(corpus)], True, None)
    assert res["status"] == "ready", res
    assert res["doc_count"] == 2, res
    assert res["chunk_count"] > 0, res
    assert res["embed_mode"] == "vector", res
    print("PASS index_source(向量):", res)
    _vsrc = await database.get_rag_source("src-vec", SPACE)
    assert _vsrc and _vsrc.get("progress") == 100 and _vsrc.get("totalFiles") == 2, _vsrc
    print("PASS 索引进度落盘:", _vsrc.get("progress"), _vsrc.get("totalFiles"))

    chunks = await database.get_rag_chunks_for_retrieval(SPACE)
    assert len(chunks) == res["chunk_count"]
    assert all(c["embedding"] for c in chunks), "存在缺失向量的切片"
    print("PASS 切片均含向量, 总数 =", len(chunks))

    # 3) 检索 + 回答（向量）
    r = await rag_service.query(SPACE, "什么是 RAG 检索增强生成？", top_k=3)
    assert r["mode"] == "vector", r["mode"]
    assert len(r["hits"]) > 0, r
    assert len(r["sources"]) > 0
    assert "[1]" in r["answer"], r["answer"]
    print("PASS query(向量):", {k: r[k] for k in ("mode", "topK", "embedAvailable")},
          "hits =", len(r["hits"]))

    # 4) 关键词降级：破坏嵌入后重新索引（API 与本地两层全断，模拟彻底无向量环境；
    #    注意：本机若配了可用本地模型，仅断 embed 不够，必须连 _try_local_embed 一起断）
    llm_client.embed = lambda texts, model=None: None
    _orig_tle = llm_client._try_local_embed
    llm_client._try_local_embed = lambda texts, eff: None
    await database.create_rag_source("src-kw", SPACE, "src-kw", [str(corpus)], True,
                                     ["pdf", "txt", "md"], status="indexing")
    res2 = await rag_service.index_source("src-kw", SPACE, [str(corpus)], True, None)
    assert res2["embed_mode"] == "keyword", res2
    r2 = await rag_service.query(SPACE, "深度学习", top_k=3)
    assert r2["mode"] == "keyword", r2["mode"]
    assert len(r2["hits"]) > 0
    print("PASS query(关键词降级):", r2["mode"], "hits =", len(r2["hits"]))

    # 5) embed_with_fallback 降级测试：API + 本地都失败 → keyword
    #    （沿用上一步的双层打桩；注意此时 src-vec 仍有向量，单断 embed 不够）
    llm_client.embed = lambda texts, model=None: None
    r3 = await rag_service.query(SPACE, "什么是 RAG？", top_k=3)
    assert r3["mode"] == "keyword", r3["mode"]
    print("PASS embed_with_fallback 降级:", r3["mode"])
    llm_client._try_local_embed = _orig_tle

    # 5) 源列表 / 统计
    srcs = await database.get_rag_sources(SPACE)
    assert len(srcs) == 2, srcs
    stats = await database.get_rag_stats(SPACE)
    assert stats["sourceCount"] == 2
    print("PASS 源列表/统计:", stats)

    # 6) 级联删除
    ok = await database.delete_rag_source("src-vec", SPACE)
    assert ok
    after = await database.get_rag_chunks_for_retrieval(SPACE)
    assert all(c["sourceId"] != "src-vec" for c in after)
    print("PASS 级联删除")

    # ---- P0 新增覆盖 ----
    # 7) kind 字段：local 默认 + 系统源幂等
    await database.create_rag_source("src-kind", SPACE, "src-kind", [], True,
                                     ["pdf"], status="ready", kind="local")
    ksrc = await database.get_rag_source("src-kind", SPACE)
    assert ksrc and ksrc.get("kind") == "local", ksrc
    psrc = await database.ensure_rag_source("__papers__", SPACE, "论文库（自动）", kind="paper")
    wsrc = await database.ensure_rag_source("__web__", SPACE, "网页收藏", kind="web")
    assert psrc["kind"] == "paper" and wsrc["kind"] == "web", (psrc, wsrc)
    psrc2 = await database.ensure_rag_source("__papers__", SPACE, "论文库（自动）", kind="paper")
    assert psrc2["id"] == "__papers__"
    print("PASS kind/系统源幂等")

    # 系统源增量落库的向量成功路径（防止只测到关键词降级而漏掉 profile 逻辑）。
    _orig_spec = rag_service._current_embedding_spec
    _orig_exact = llm_client.embed_exact
    rag_service._current_embedding_spec = lambda: {
        "provider": "api", "model": "qa-embed", "revision": "qa-rev",
        "query_instruction": "", "normalized": True,
    }
    llm_client.embed_exact = lambda texts, **kwargs: fake_embed(texts)
    try:
        sys_res = await rag_service._embed_and_store(SPACE, "__web__", [({
            "id": "web-vector-doc", "file_path": "https://example.com/vector",
            "file_name": "vector.html", "file_type": "html", "file_size": 20,
            "page_count": 1, "char_count": 20, "url": "https://example.com/vector",
            "title": "Vector", "section": "web", "content_hash": "qa-vector",
        }, [{"content": "vector system source", "page_start": 1, "page_end": 1,
             "char_start": 0, "char_end": 20}])])
        assert sys_res["embed_mode"] == "vector" and sys_res["chunk_count"] == 1, sys_res
    finally:
        rag_service._current_embedding_spec = _orig_spec
        llm_client.embed_exact = _orig_exact
    print("PASS 系统源增量向量落库")

    # 8) URL 规范化 + 正文抽取（标准库，无网络）
    assert rag_service.normalize_url("https://Example.com/a/?utm_source=x#frag") == \
        "https://example.com/a", rag_service.normalize_url("https://Example.com/a/?utm_source=x#frag")
    assert rag_service.normalize_url("ftp://x") == ""
    title, body, method = rag_service.extract_main_content(
        "<html><head><title> Hello </title></head><body><nav>skip</nav>"
        "<article><p>正文第一段。</p><p>正文第二段。</p></article></body></html>")
    assert title == "Hello" and "正文第一段" in body and "skip" not in body, (title, body)
    assert method in ("stdlib", "trafilatura")
    print("PASS normalize_url/extract_main_content:", method)

    # 9) overlap 切分：内容相同但块数/长度符合预期，且兼容旧调用
    long_text = "段落一。" * 400
    bounds = [(1, 0, len(long_text))]
    no_ov = rag_service.chunk_document(long_text, bounds)
    with_ov = rag_service.chunk_document(long_text, bounds, chunk_size=1000, overlap=150,
                                         prefix="[T|S] ")
    assert len(with_ov) >= len(no_ov) and all(c["content"].startswith("[T|S] ") for c in with_ov)
    old_call = rag_service.chunk_document("abc", [(1, 0, 3)])
    assert old_call[0]["content"] == "abc"
    print("PASS chunk overlap/prefix:", len(no_ov), "->", len(with_ov))

    # 10) FTS5 + RRF：写入后可检索（无 FTS5 则跳过不断言）
    fts_hits = await database.fts_search_chunk_ids(SPACE, "深度学习", limit=10)
    assert isinstance(fts_hits, list)
    print("PASS fts_search:", len(fts_hits))
    # RRF 融合：向量+关键词双路应稳定返回（mode 保持兼容）
    llm_client.embed = fake_embed
    r4 = await rag_service.query(SPACE, "深度学习", top_k=3)
    assert r4["mode"] in ("vector", "keyword") and len(r4["hits"]) > 0
    assert all("url" in h and "title" in h for h in r4["hits"])
    print("PASS RRF融合检索:", r4["mode"])

    # 11) vector_index：暴力余弦 + faiss 缺省回退
    from backend.server.rag import vector_index as _vi
    assert abs(_vi.cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-6
    assert _vi.backend_name() == "brute"  # 默认不自动启用 faiss
    assert _vi.faiss_topk([1.0], [("a", [1.0])], 1) is None  # 未显式启用返回 None
    print("PASS vector_index 默认行为")

    # 12) 本地模型只读扫描/探针（不触发下载、不加载 torch）
    from backend.server.rag import local_embed as _le
    scanned = _le.scan_local_models()
    assert isinstance(scanned, list)
    p0 = _le.probe_local_model("")
    assert p0["configured"] is False and p0["resolvable"] is False
    p1 = _le.probe_local_model("Qwen/Qwen3-Embedding-0.6B")
    assert p1["configured"] is True and "path" in p1  # 是否已下载取决于环境，不断言
    p2 = _le.probe_local_model("Qwen/Qwen3-Embedding-0.6B", "refs/pr:unsafe")
    assert p2["path"] != p1["path"] and ":" not in Path(p2["path"]).name, p2
    print("PASS local_embed 扫描/探针:", len(scanned), "个已下载;", p1["reason"])

    # 13) 后台下载状态机（mock 真实下载：失败落 failed、可重调重试）
    # backend config DATA_DIR 同步隔离，避免污染真实 data/models
    from backend.server.core import config as _cfg
    _orig_dd = _cfg.DATA_DIR
    _cfg.DATA_DIR = TMP / "dl_isolated"
    _orig_dl = _le.LocalEmbedder._download_modelscope
    try:
        _le.LocalEmbedder._download_modelscope = lambda self, mid, td, rev="": (_ for _ in ()).throw(
            RuntimeError("mock 网络中断"))
        dst = _le.download_in_background("Mock/Some-Model")
        assert dst["state"] == "downloading", dst
        import time as _time
        deadline = _time.time() + 20
        cur = dst
        while _time.time() < deadline:
            await asyncio.sleep(0.5)
            cur = _le.get_download_status("Mock/Some-Model")
            if cur["state"] in ("ready", "failed"):
                break
        assert cur["state"] == "failed" and "mock" in cur["error"], cur
    finally:
        _le.LocalEmbedder._download_modelscope = _orig_dl
        _cfg.DATA_DIR = _orig_dd
    print("PASS 后台下载 downloading -> failed，可手动重试")

    # 14) 标准库下载兜底（mock urlopen：写入 / 断点续传 / 路径穿越拦截）
    import io as _io
    import json as _json
    from unittest import mock as _mock

    _FILES = {"config.json": b'{"model": "mock"}',
              "sub/model.safetensors": b"x" * 3000}

    class _FakeResp:
        def __init__(self, data: bytes, status: int = 200):
            self._data = data
            self.status = status

        def read(self, n: int = -1) -> bytes:
            if n is None or n < 0:
                out, self._data = self._data, b""
                return out
            out, self._data = self._data[:n], self._data[n:]
            return out

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    _seen_range: list = []

    def _fake_urlopen(req, timeout=None):
        url = req.full_url
        if url.endswith("/api/models/Mock/Std"):
            body = _json.dumps(
                {"siblings": [{"rfilename": f} for f in _FILES]}).encode()
            return _FakeResp(body)
        if "/resolve/main/" in url:
            rel = url.split("/resolve/main/", 1)[1]
            data = _FILES[rel]
            rng = req.get_header("Range")
            if rng:
                _seen_range.append(rng)
                start = int(rng.split("=")[1].split("-")[0])
                return _FakeResp(data[start:], 206)
            return _FakeResp(data, 200)
        raise AssertionError(f"unexpected url {url}")

    _emb = _le.LocalEmbedder()
    _std_dir = TMP / "stdlib_model"
    with _mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        _emb._download_stdlib("Mock/Std", _std_dir)
    assert (_std_dir / "config.json").read_bytes() == _FILES["config.json"]
    assert (_std_dir / "sub" / "model.safetensors").read_bytes() == _FILES["sub/model.safetensors"]
    print("PASS 标准库下载写入（含子目录）")
    # 断点续传：截半后重下，应带 Range 且内容补全
    _seen_range.clear()
    (_std_dir / "sub" / "model.safetensors").write_bytes(b"x" * 1500)
    with _mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        _emb._download_stdlib("Mock/Std", _std_dir)
    assert "bytes=1500-" in _seen_range, _seen_range
    assert (_std_dir / "sub" / "model.safetensors").read_bytes() == _FILES["sub/model.safetensors"]
    print("PASS 断点续传:", [r for r in _seen_range if "1500" in r][0])

    def _fake_evil(req, timeout=None):
        if req.full_url.endswith("/api/models/Mock/Evil"):
            return _FakeResp(_json.dumps({"siblings": [{"rfilename": "../evil.txt"}]}).encode())
        raise AssertionError(req.full_url)

    with _mock.patch("urllib.request.urlopen", side_effect=_fake_evil):
        try:
            _emb._download_stdlib("Mock/Evil", TMP / "evil_model")
            raise AssertionError("路径穿越未被拦截")
        except RuntimeError as e:
            assert "穿越" in str(e), e
    print("PASS 路径穿越拦截")

    # 15) 进行中扫描 + 过期改写 + 单飞行 + 残缺识别（backend DATA_DIR 隔离）
    from backend.server.core import config as _cfg
    import threading as _th
    _orig_dd = _cfg.DATA_DIR
    _cfg.DATA_DIR = TMP / "dlstate"
    try:
        _md = TMP / "dlstate" / "models"
        _md.mkdir(parents=True, exist_ok=True)
        _now = int(__import__("time").time() * 1000)
        (_md / ".status_Fresh_Model.json").write_text(_json.dumps(
            {"model": "Fresh/Model", "state": "downloading", "sizeMB": 10.0,
             "error": "", "updatedAt": _now}), encoding="utf-8")
        (_md / ".status_Old_Model.json").write_text(_json.dumps(
            {"model": "Old/Model", "state": "downloading", "sizeMB": 5.0,
             "error": "", "updatedAt": _now - 600_000}), encoding="utf-8")
        act = _le.get_active_download()
        assert act and act["model"] == "Fresh/Model", act
        (_md / ".status_Fresh_Model.json").unlink()
        assert _le.get_active_download() is None
        _stale = _json.loads((_md / ".status_Old_Model.json").read_text(encoding="utf-8"))
        assert _stale["state"] == "failed" and "中断" in _stale["error"], _stale
        print("PASS 进行中扫描 + 过期改写")
        # 残缺目录：仅 config.json 无权重 -> incomplete
        (_md / "Part_Model").mkdir(exist_ok=True)
        (_md / "Part_Model" / "config.json").write_text("{}", encoding="utf-8")
        _part = [m for m in _le.scan_local_models() if m["id"] == "Part_Model"]
        assert _part and _part[0]["downloaded"] is False and _part[0]["incomplete"] is True, _part
        print("PASS 残缺下载识别")
        # 单飞行：A 占住线程，B 提交回 busy
        _ev = _th.Event()
        _orig_ms = _le.LocalEmbedder._download_modelscope
        _le.LocalEmbedder._download_modelscope = lambda self, mid, td, rev="": _ev.wait(15)
        try:
            _a = _le.download_in_background("Busy/A")
            assert _a["state"] == "downloading", _a
            _b = _le.download_in_background("Busy/B")
            assert _b["state"] == "busy" and _b.get("activeModel") == "Busy/A", _b
            print("PASS 单飞行 busy:", _b.get("activeModel"))
        finally:
            _ev.set()
            _le.LocalEmbedder._download_modelscope = _orig_ms
            await asyncio.sleep(0.2)
    finally:
        _cfg.DATA_DIR = _orig_dd

    # 16) with_busy_retry：两次 locked 后成功；非锁错误直抛不重试
    _flaky_calls = {"n": 0}

    async def _flaky() -> str:
        _flaky_calls["n"] += 1
        if _flaky_calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert await database.with_busy_retry(_flaky, attempts=5, what="qa") == "ok"
    assert _flaky_calls["n"] == 3, _flaky_calls

    async def _fatal() -> str:
        raise sqlite3.OperationalError("no such table: t")

    try:
        await database.with_busy_retry(_fatal, attempts=3, what="qa")
        raise AssertionError("非锁错误应直接抛出")
    except sqlite3.OperationalError as e:
        assert "no such table" in str(e), e
    print("PASS with_busy_retry（锁重试 + 非锁直抛）")

    # 17) instance_guard：心跳登记/同胞检测/过期修剪（backend DATA_DIR 隔离）
    from backend.server.core import config as _cfg2
    from backend.server.core import instance_guard as _ig
    import os as _os
    _orig_dd2 = _cfg2.DATA_DIR
    _orig_app_port = _os.environ.get("APP_PORT")
    _cfg2.DATA_DIR = TMP / "guard"
    try:
        _entries = _ig.beat()
        _me = str(_ig.supervisor_pid())
        assert _me in _entries, _entries
        assert _ig.list_siblings() == [], _ig.list_siblings()
        _entries2 = _ig.beat()
        assert _entries2[_me]["startedAt"] == _entries[_me]["startedAt"], "重复 beat 不应刷新 startedAt"
        # 伪造异端口同胞（用本进程 pid：必存活）+ 过期残留 + 已死 pid
        _now2 = int(__import__("time").time() * 1000)
        _live_pid = str(
            _os.getppid() if _ig.supervisor_pid() == _os.getpid() else _os.getpid())
        assert _live_pid != _me, "测试假设：supervisor pid 与本进程不同"
        _all = _ig._read_all()
        _all[_live_pid] = {"port": 8001, "startedAt": _now2, "updatedAt": _now2}
        _all["88888888"] = {"port": 8002, "startedAt": _now2 - 600_000, "updatedAt": _now2 - 600_000}
        _all["99999999"] = {"port": 8003, "startedAt": _now2, "updatedAt": _now2}  # 心跳新鲜但 pid 已死
        _ig._write_all(_all)
        assert _ig._pid_alive(int(_live_pid)) is True
        assert _ig._pid_alive(999999999) is False
        _sibs = _ig.list_siblings()
        assert len(_sibs) == 1 and _sibs[0]["supervisorPid"] == _live_pid, _sibs
        _remaining = _ig._read_all()
        assert "88888888" not in _remaining, "过期心跳应被修剪"
        assert "99999999" not in _remaining, "已死 pid 应被修剪（重启误报消除）"
        # 端口探测兜底（argv 无 --port 时）
        if "APP_PORT" in _os.environ:
            del _os.environ["APP_PORT"]
        assert _ig.detect_port() == 8000, sys.argv
        print("PASS instance_guard 心跳/同胞/过期/端口兜底")
    finally:
        _cfg2.DATA_DIR = _orig_dd2
        if _orig_app_port is not None:
            _os.environ["APP_PORT"] = _orig_app_port

    # 18) 分批清空抗争用：1500 切片 + 并发写 hammer 下完整清掉、无异常
    import threading as _th2
    await database.create_rag_source("src-big", SPACE, "src-big", [], True, [], status="ready")
    await database.create_rag_document("doc-big", SPACE, "src-big", "/tmp/big.txt",
                                       "big.txt", "txt", 100, 1, 60000, 0)
    _big = [{"id": f"big-{i}", "source_id": "src-big", "doc_id": "doc-big",
             "chunk_index": i, "content": f"concurrencytest 切片 {i} 内容填充",
             "page_start": 1, "page_end": 1, "char_start": i, "char_end": i + 10,
             "embedding": None, "token_count": 5} for i in range(1500)]
    assert await database.insert_rag_chunks(_big, SPACE) == 1500
    _stop_hammer = _th2.Event()

    def _hammer() -> None:
        import sqlite3 as _sq3
        con = _sq3.connect(str(database.DB_PATH), timeout=30.0)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            _i = 0
            while not _stop_hammer.is_set():
                try:
                    con.execute("UPDATE rag_sources SET updated_at = ? WHERE id = ?",
                                (_i, "src-big"))
                    con.commit()
                except Exception:
                    pass
                _i += 1
        finally:
            con.close()

    _ht = _th2.Thread(target=_hammer, daemon=True)
    _ht.start()
    try:
        _cleared = await database.clear_rag_chunks("src-big", SPACE)
    finally:
        _stop_hammer.set()
        _ht.join(timeout=10)
    assert _cleared == 1500, _cleared
    _rest = [c for c in await database.get_rag_chunks_for_retrieval(SPACE) if c["sourceId"] == "src-big"]
    assert not _rest, len(_rest)
    _fts_left = await database.fts_search_chunk_ids(SPACE, "concurrencytest", limit=100)
    assert not _fts_left, _fts_left
    assert await database.delete_rag_source("src-big", SPACE)
    print("PASS 分批清空抗争用（1500 切片 + FTS 联动）")

    # 19) FTS 显式同步（无触发器）：插入即检出，单文档删除即清，无孤儿
    async with database.get_db() as _c:
        _trgs = await database._fetchall(
            _c, "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_rag_chunks_fts_%'")
        assert not _trgs, [dict(r) for r in _trgs]
    await database.create_rag_source("src-fts", SPACE, "src-fts", [], True, [], status="ready")
    await database.create_rag_document("doc-fts", SPACE, "src-fts", "/tmp/f.txt",
                                       "f.txt", "txt", 10, 1, 100, 0)
    _fch = [{"id": f"fts-{i}", "source_id": "src-fts", "doc_id": "doc-fts",
             "chunk_index": i, "content": f"zebrastripe 斑马纹 {i}",
             "page_start": 1, "page_end": 1, "char_start": i, "char_end": i + 5,
             "embedding": None, "token_count": 3} for i in range(5)]
    assert await database.insert_rag_chunks(_fch, SPACE) == 5
    _found = await database.fts_search_chunk_ids(SPACE, "zebrastripe", limit=10)
    assert len(_found) == 5, _found
    assert await database.delete_rag_document("doc-fts", SPACE)
    _found2 = await database.fts_search_chunk_ids(SPACE, "zebrastripe", limit=10)
    assert not _found2, _found2
    assert await database.delete_rag_source("src-fts", SPACE)
    print("PASS FTS 显式同步（无触发器）")

    # 20) any_vec 门：零向量库检索不得调用 embedding（省 API token/本地加载）
    from backend.server.llm import llm_client as _lc
    await database.create_rag_source("src-kw2", SPACE, "src-kw2", [], True, [], status="ready")
    await database.create_rag_document("doc-kw2", SPACE, "src-kw2", "/tmp/k.txt",
                                       "k.txt", "txt", 10, 1, 100, 0)
    _kch = [{"id": f"kw2-{i}", "source_id": "src-kw2", "doc_id": "doc-kw2",
             "chunk_index": i, "content": f"门禁测试无向量内容 {i} apple",
             "page_start": 1, "page_end": 1, "char_start": i, "char_end": i + 5,
             "embedding": None, "token_count": 3} for i in range(3)]
    assert await database.insert_rag_chunks(_kch, SPACE) == 3
    assert await database.has_rag_vectors(SPACE, ["src-kw2"]) is False
    _calls = {"n": 0}
    _orig_ewf = _lc.embed_with_fallback

    def _counting_ewf(texts, model=None):
        _calls["n"] += 1
        raise AssertionError("零向量库不应调用 embedding")
    _lc.embed_with_fallback = _counting_ewf
    try:
        _hits, _mode, _ea, _be = await rag_service.retrieve(
            SPACE, "apple", top_k=3, source_ids=["src-kw2"])
    finally:
        _lc.embed_with_fallback = _orig_ewf
    assert _calls["n"] == 0, _calls
    assert len(_hits) > 0 and _mode == "keyword", (_hits, _mode)
    assert await database.delete_rag_source("src-kw2", SPACE)
    print("PASS any_vec 门（零调用 + 关键词可用）")

    # 21) _embed_texts 按 provider 切 batch + on_batch 回调（全 mock，零网络）
    from unittest import mock as _mock2
    _lc.embed_with_fallback = lambda texts, model=None: [[0.1] * 4 for _ in texts]
    try:
        _cb_calls: list = []

        async def _cb(done: int, total: int) -> None:
            _cb_calls.append((done, total))

        with _mock2.patch.object(
                type(_lc), "embedding_provider",
                new_callable=_mock2.PropertyMock, return_value="api"):
            _v = await rag_service._embed_texts(
                [f"t{i}" for i in range(40)], on_batch=_cb)
        assert _v is not None and len(_v) == 40, _v
        assert [d for d, _ in _cb_calls] == [16, 32, 40], _cb_calls
        assert all(t == 40 for _, t in _cb_calls)
        print("PASS API batch=16 + 回调累计值")
        _cb_calls.clear()
        with _mock2.patch.object(
                type(_lc), "embedding_provider",
                new_callable=_mock2.PropertyMock, return_value="local"):
            _v2 = await rag_service._embed_texts(
                [f"t{i}" for i in range(40)], on_batch=_cb)
        assert _v2 is not None and len(_v2) == 40, _v2
        assert [d for d, _ in _cb_calls] == [40], _cb_calls
        print("PASS 本地 batch=64 + 回调累计值")
    finally:
        del _lc.embed_with_fallback  # 恢复类方法，避免污染后继用例

    # 22) Resumable generation: a fully persisted file is not parsed again,
    # and staged chunks remain invisible until the generation is activated.
    _resume_source = "src-resume"
    await database.create_rag_source(
        _resume_source, SPACE, _resume_source, [str(corpus)], True,
        ["txt", "md"], status="indexing")
    _resume_job = await database.enqueue_rag_index(
        SPACE, _resume_source, [str(corpus)], True, ["txt", "md"])
    _claimed = await database.claim_rag_index_job("qa-resume-worker")
    assert _claimed and _claimed["id"] == _resume_job, _claimed
    assert await database.mark_rag_job_running(_resume_job, SPACE)
    _generation = await database.ensure_rag_job_generation(_resume_job, SPACE)
    assert _generation
    assert await database.ensure_rag_job_generation(_resume_job, SPACE) == _generation

    _first_path = (corpus / "a.txt").resolve()
    _first_meta = rag_service.extract_document(_first_path)
    _first_doc_id = "resume-doc-a"
    _first_chunks = rag_service.chunk_document(
        _first_meta["full_text"], _first_meta["page_boundaries"], overlap=150)
    assert await database.store_rag_document_chunks({
        "id": _first_doc_id,
        "source_id": _resume_source,
        "file_path": str(_first_path),
        "file_name": _first_path.name,
        "file_type": _first_meta["file_type"],
        "file_size": _first_meta["file_size"],
        "page_count": _first_meta["page_count"],
        "char_count": _first_meta["char_count"],
        "generation_id": _generation,
    }, [{
        "id": f"resume-a-{i}", "source_id": _resume_source,
        "doc_id": _first_doc_id, "chunk_index": i,
        "content": chunk["content"], "page_start": chunk["page_start"],
        "page_end": chunk["page_end"], "char_start": chunk["char_start"],
        "char_end": chunk["char_end"], "generation_id": _generation,
        "token_count": max(1, len(chunk["content"]) // 4),
    } for i, chunk in enumerate(_first_chunks)], SPACE)
    _before_activation = await database.get_rag_chunks_for_retrieval(
        SPACE, [_resume_source])
    assert not _before_activation, "staging generation leaked before activation"

    _orig_extract = rag_service.extract_document
    _orig_resume_spec = rag_service._current_embedding_spec
    _orig_resume_exact = llm_client.embed_exact
    _extracted_paths = []

    def _count_extract(path):
        _extracted_paths.append(str(Path(path).resolve()))
        return _orig_extract(path)

    rag_service.extract_document = _count_extract
    rag_service._current_embedding_spec = lambda: {
        "provider": "api", "model": "qa-resume", "revision": "qa-v1",
        "query_instruction": "", "normalized": True,
    }
    llm_client.embed_exact = lambda texts, **kwargs: fake_embed(texts)
    try:
        _resumed = await rag_service.index_source(
            _resume_source, SPACE, [str(corpus)], True, ["txt", "md"],
            job_id=_resume_job, generation_id=_generation)
    finally:
        rag_service.extract_document = _orig_extract
        rag_service._current_embedding_spec = _orig_resume_spec
        llm_client.embed_exact = _orig_resume_exact
    assert _resumed["status"] == "ready", _resumed
    assert str(_first_path) not in _extracted_paths, _extracted_paths
    assert str((corpus / "sub" / "b.md").resolve()) in _extracted_paths, _extracted_paths
    _resume_state = await database.get_rag_generation_state(
        _resume_source, SPACE, _generation)
    assert _resume_state["documentCount"] == 2, _resume_state
    assert _resume_state["embeddedCount"] == _resume_state["chunkCount"], _resume_state
    _resume_job_row = await database.get_rag_index_job(_resume_job, SPACE)
    assert _resume_job_row and _resume_job_row["phase"] == "done", _resume_job_row
    assert _resume_job_row["checkpoint"].get("completed") is True, _resume_job_row
    print("PASS resumable generation + invisible staging + durable checkpoint")

    # 23) Structured local chunking keeps Markdown sections separate and bounded.
    _structured_text = (
        "# Section A\n\n" + ("alpha sentence. " * 500)
        + "\n\n# Section B\n\n" + ("第二节内容。" * 500)
    )
    _structured = rag_service.chunk_local_document(
        _structured_text, [(1, 0, len(_structured_text))])
    assert len(_structured) > 2
    assert all(rag_service._estimate_tokens(c["content"]) <= 400 for c in _structured)
    assert not any(
        "# Section A" in c["content"] and "# Section B" in c["content"]
        for c in _structured)
    assert any(c["content"].startswith("# Section A") for c in _structured)
    assert any(c["content"].startswith("# Section B") for c in _structured)
    print("PASS structured token-budgeted local chunking")

    # 24) A no-change rescan performs no extraction/embedding; duplicate content
    # reuses the exact embedding cache for the same immutable profile.
    _incremental_source = "src-incremental"
    await database.create_rag_source(
        _incremental_source, SPACE, _incremental_source, [str(corpus)], True,
        ["txt", "md"], status="indexing")
    _orig_inc_spec = rag_service._current_embedding_spec
    _orig_inc_exact = llm_client.embed_exact
    _inc_embed_calls = {"texts": 0}

    def _incremental_embed(texts, **kwargs):
        _inc_embed_calls["texts"] += len(texts)
        return fake_embed(texts)

    rag_service._current_embedding_spec = lambda: {
        "provider": "api", "model": "qa-incremental", "revision": "qa-v1",
        "query_instruction": "", "normalized": True,
    }
    llm_client.embed_exact = _incremental_embed
    try:
        _inc_first = await rag_service.index_source(
            _incremental_source, SPACE, [str(corpus)], True, ["txt", "md"])
        assert _inc_first["status"] == "ready" and _inc_embed_calls["texts"] > 0, _inc_first

        _original_extract = rag_service.extract_document

        def _unexpected_extract(path):
            raise AssertionError(f"unchanged file was extracted again: {path}")

        rag_service.extract_document = _unexpected_extract
        _inc_embed_calls["texts"] = 0
        try:
            _inc_second = await rag_service.index_source(
                _incremental_source, SPACE, [str(corpus)], True, ["txt", "md"])
        finally:
            rag_service.extract_document = _original_extract
        assert _inc_second["status"] == "ready", _inc_second
        assert _inc_second["reused_files"] == 2, _inc_second
        assert _inc_embed_calls["texts"] == 0, _inc_embed_calls

        _duplicate = corpus / "copy.txt"
        _duplicate.write_text((corpus / "a.txt").read_text(encoding="utf-8"), encoding="utf-8")
        _inc_embed_calls["texts"] = 0
        _inc_third = await rag_service.index_source(
            _incremental_source, SPACE, [str(corpus)], True, ["txt", "md"])
        assert _inc_third["status"] == "ready", _inc_third
        assert _inc_third["reused_files"] == 2, _inc_third
        assert _inc_third["cache_hits"] >= 1, _inc_third
        assert _inc_embed_calls["texts"] == 0, _inc_embed_calls
    finally:
        rag_service._current_embedding_spec = _orig_inc_spec
        llm_client.embed_exact = _orig_inc_exact
    print("PASS file fingerprints + generation reuse + embedding cache")

    print("\nALL_RAG_QA_PASS")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
