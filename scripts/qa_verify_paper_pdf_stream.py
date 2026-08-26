"""QA 验证：GET /api/papers/{arxiv_id}/pdf 预览路由。

根因回归（2026-08-25）：之前这个路由不存在，前端 PDF.js 永远停在
numPages=0 + 加载动画。修复后必须：

1. 已下载（localPath 存在且文件存在）：直接返回 200 + application/pdf 字节流
2. 未下载（localPath 为空）：按需下载并落盘，再返回字节流
3. localPath 指向的文件已丢失：返回 5xx（不静默 404）
4. arxiv_id 不存在 / 跨空间访问：返回 404
5. Content-Type 必须是 application/pdf，不能是 text/html

使用 TestClient + 临时 DB + monkeypatch，无外部网络，无真实数据写入。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# 在 import database / backend 之前把数据库重定向到临时位置，避免污染真实 data
_TMP_DB_DIR = Path(tempfile.mkdtemp(prefix="qa_paper_pdf_"))
_TMP_DB_PATH = _TMP_DB_DIR / "qa.db"
os.environ.setdefault("AI_RESEARCH_OS_DATA_DIR", str(_TMP_DB_DIR))

from fastapi.testclient import TestClient

import database  # noqa: E402


def _make_test_pdf(tmpdir: Path, name: str = "fake.pdf") -> Path:
    """最小合法 PDF 字节（PDF.js 可识别）。"""
    path = tmpdir / name
    minimal_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n181\n%%EOF\n"
    )
    path.write_bytes(minimal_pdf)
    return path


async def _seed_paper(tmpdir: Path, space_id: str, arxiv_id: str, *, with_local: bool):
    """在隔离的临时 DB 里写入一篇测试论文。"""
    # 用一个独立 sqlite 文件，不要碰真实 DB_PATH
    db_file = tmpdir / "seed.db"
    # 暂存当前 DB_PATH，写完后还原
    orig_db_path = database.DB_PATH
    database.DB_PATH = db_file
    try:
        await database.init_db()
        # 删干净，重跑测试也不冲突
        async with database.get_db() as conn:
            await conn.execute("DELETE FROM papers WHERE arxiv_id = ?", (arxiv_id,))
            await conn.execute("DELETE FROM papers WHERE id = ?", (f"test-{arxiv_id}",))
        paper = {
            "id": f"test-{arxiv_id}",
            "arxivId": arxiv_id,
            "title": "Test Paper",
            "abstract": "test abstract",
            "authors": ["Doe, John"],
            "year": 2024,
            "pdfUrl": "https://arxiv.org/pdf/" + arxiv_id + ".pdf",
            "categories": ["cs.CV"],
            "publishedDate": "2024-01-01T00:00:00Z",
            "tags": [],
            "isRead": False,
            "isFavorite": False,
            "summary": None,
            "bibtex": None,
            "localPath": None,
        }
        if with_local:
            path = _make_test_pdf(tmpdir, f"{arxiv_id}.pdf")
            paper["localPath"] = str(path)
        ok = await database.insert_paper(paper, space_id=space_id)
        if not ok:
            raise RuntimeError(f"seed insert returned False")
        return paper
    finally:
        database.DB_PATH = orig_db_path


def _get_app():
    sys.path.insert(0, str(ROOT))
    from backend.server.main import app
    return app


def _client():
    return TestClient(_get_app(), raise_server_exceptions=False)


def _patch_db(db_file: Path):
    """上下文管理器：把 backend.server.db.database.DB_PATH 切到临时文件。"""
    # backend.server.db.database 引用的是同一个 database 模块
    backend_db = sys.modules.get("backend.server.db")
    if backend_db is None:
        import backend.server.db as bd  # noqa
        backend_db = bd
    # 它的 database 属性就是 scripts.database 模块
    return patch.object(backend_db.database, "DB_PATH", db_file)


# ---------------- 测试 ----------------


def test_pdf_stream_already_local():
    """[1] 已下载：localPath 存在 → 直接返回 200 + PDF。"""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        asyncio.run(_seed_paper(tdp, "qa-stream-1", "1111.2222", with_local=True))
        client = _client()
        with _patch_db(tdp / "seed.db"):
            r = client.get(
                "/api/papers/1111.2222/pdf",
                headers={"X-Space-Key": "qa-stream-1"},
            )
        if r.status_code != 200:
            raise AssertionError(f"status={r.status_code} body={r.text[:200]}")
        if "application/pdf" not in r.headers.get("content-type", ""):
            raise AssertionError(f"content-type={r.headers.get('content-type')}")
        if not r.content.startswith(b"%PDF-"):
            raise AssertionError(f"body 不是 PDF: {r.content[:20]!r}")
    print("  [1] 已下载：localPath 存在 → 200 + application/pdf ✓")


def test_pdf_stream_lazy_download():
    """[2] 未下载：localPath 为空 → 按需下载 → 返回 200 + PDF。"""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        asyncio.run(_seed_paper(tdp, "qa-stream-2", "3333.4444", with_local=False))
        fake_pdf = _make_test_pdf(tdp, "3333.4444.pdf")

        def fake_download(arxiv_id, pdf_url, data_dir, space_id="default"):
            return str(fake_pdf)

        client = _client()
        with _patch_db(tdp / "seed.db"):
            with patch("scripts.fetch_arxiv.download_pdf", side_effect=fake_download):
                r = client.get(
                    "/api/papers/3333.4444/pdf",
                    headers={"X-Space-Key": "qa-stream-2"},
                )
        if r.status_code != 200:
            raise AssertionError(f"status={r.status_code} body={r.text[:200]}")
        if "application/pdf" not in r.headers.get("content-type", ""):
            raise AssertionError(f"content-type={r.headers.get('content-type')}")
        if not r.content.startswith(b"%PDF-"):
            raise AssertionError(f"body 不是 PDF: {r.content[:20]!r}")
    print("  [2] 未下载：懒下载 + 200 + application/pdf ✓")


def test_pdf_stream_not_found():
    """[3] arxiv_id 不存在 → 404。"""
    client = _client()
    r = client.get(
        "/api/papers/0000.0000-not-exist/pdf",
        headers={"X-Space-Key": "qa-stream-3"},
    )
    if r.status_code != 404:
        raise AssertionError(f"应该 404，实际 {r.status_code} body={r.text[:200]}")
    print("  [3] arxiv_id 不存在 → 404 ✓")


def test_pdf_stream_space_isolation():
    """[4] 跨空间访问 → 404（不能跨空间读 PDF）。"""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        asyncio.run(_seed_paper(tdp, "qa-stream-4-owner", "5555.6666", with_local=True))
        client = _client()
        with _patch_db(tdp / "seed.db"):
            r = client.get(
                "/api/papers/5555.6666/pdf",
                headers={"X-Space-Key": "qa-stream-4-attacker"},
            )
        if r.status_code != 404:
            raise AssertionError(f"跨空间应该 404，实际 {r.status_code}")
    print("  [4] 跨空间访问 → 404（不泄漏）✓")


def test_pdf_stream_file_missing():
    """[5] localPath 指向的文件被外部删除 → 4xx/5xx（不假装成功）。"""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        paper = asyncio.run(_seed_paper(tdp, "qa-stream-5", "7777.8888", with_local=True))
        local = Path(paper["localPath"])
        if local.exists():
            local.unlink()

        def fake_download_fail(*args, **kwargs):
            return None

        client = _client()
        with _patch_db(tdp / "seed.db"):
            with patch("scripts.fetch_arxiv.download_pdf", side_effect=fake_download_fail):
                r = client.get(
                    "/api/papers/7777.8888/pdf",
                    headers={"X-Space-Key": "qa-stream-5"},
                )
        if r.status_code < 400:
            raise AssertionError(f"文件丢失应该报错，实际 {r.status_code} body={r.text[:200]}")
    print("  [5] localPath 文件丢失 → 4xx/5xx（不假装成功）✓")


def main():
    print("=" * 60)
    print("  Paper PDF 预览路由 QA（2026-08-25 回归）")
    print("=" * 60)
    tests = [
        test_pdf_stream_already_local,
        test_pdf_stream_lazy_download,
        test_pdf_stream_not_found,
        test_pdf_stream_space_isolation,
        test_pdf_stream_file_missing,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  [X] {t.__name__}: FAILED - {exc}")
            failed += 1
        except Exception as exc:
            import traceback
            print(f"  [X] {t.__name__}: ERROR - {type(exc).__name__}: {exc}")
            traceback.print_exc()
            failed += 1
    print("=" * 60)
    if failed:
        print(f"  FAIL: {failed} 项未通过")
        sys.exit(1)
    print(f"  ALL PASS ({len(tests)}/{len(tests)})")
    print("=" * 60)


if __name__ == "__main__":
    main()
