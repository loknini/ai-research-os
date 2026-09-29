#!/usr/bin/env python3
"""可选依赖缺失的优雅降级验证（零安装环境可跑，无需网络）。

覆盖：
  * MuPDF C 层 stderr 噪声抑制（残缺 PDF 警告不刷屏，且 fd 2 正确恢复）
  * local_embed 加载失败留痕（last_error，供设置页提示安装 torch 等）
  * SwanLab 缺失时返回 venv 感知的友好提示（而非 traceback）
运行：python -m scripts.qa_verify_optional_deps
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parent.parent

from backend.server.rag import local_embed as _le  # noqa: E402
from backend.server.rag import service as rag_service  # noqa: E402


def test_mupdf_stderr_suppressed() -> None:
    r, w = os.pipe()
    saved = os.dup(2)
    os.dup2(w, 2)
    try:
        with rag_service._suppress_native_stderr():
            os.write(2, b"MUTED")
        os.write(2, b"KEPT")
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(w)
    data = b""
    while True:
        chunk = os.read(r, 1024)
        if not chunk:
            break
        data += chunk
    os.close(r)
    assert data == b"KEPT", data
    print("PASS MuPDF 噪声抑制（C 层写入被吞，恢复后正常）")


def test_stderr_restored_on_error() -> None:
    r, w = os.pipe()
    saved = os.dup(2)
    os.dup2(w, 2)
    try:
        try:
            with rag_service._suppress_native_stderr():
                raise ValueError("boom")
        except ValueError:
            pass
        os.write(2, b"AFTER")
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(w)
    data = b""
    while True:
        chunk = os.read(r, 1024)
        if not chunk:
            break
        data += chunk
    os.close(r)
    assert data == b"AFTER", data
    print("PASS 异常时 fd 2 照常恢复")


def test_local_embed_last_error() -> None:
    emb = _le.LocalEmbedder()
    with mock.patch("backend.server.rag.local_embed._ensure_imports",
                    side_effect=ImportError("No module named 'torch'")):
        ok = emb.load("whatever")
    assert ok is False
    assert "torch" in emb.last_error, emb.last_error
    assert _le.LocalEmbedder().last_error == "", "新实例默认无错误"
    print("PASS local_embed 错误留痕:", emb.last_error)


def test_swanlab_friendly_message() -> None:
    import importlib.util
    if importlib.util.find_spec("swanlab") is not None:
        print("SKIP swanlab 已安装（本用例仅覆盖缺失路径）")
        return
    from scripts.swanlab_integration import SwanLabIntegration
    res = SwanLabIntegration(api_key="dummy").test_connection()
    assert res["success"] is False
    assert "swanlab" in res["message"].lower(), res["message"]
    assert "pip install" in res["message"], res["message"]
    print("PASS SwanLab 缺失友好提示:", res["message"][:80])


def main() -> None:
    test_mupdf_stderr_suppressed()
    test_stderr_restored_on_error()
    test_local_embed_last_error()
    test_swanlab_friendly_message()
    print("\nALL_OPTIONAL_DEPS_QA_PASS")


if __name__ == "__main__":
    main()
