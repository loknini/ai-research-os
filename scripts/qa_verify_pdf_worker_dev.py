"""
qa_verify_pdf_worker_dev.py - 钉死 PDF.js worker 在 dev/prod 双模式都能加载

为什么需要这个回归：
  之前用 `import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url'`，
  Vite dev 模式下会返回相对 URL（如 `/node_modules/pdfjs-dist/build/pdf.worker.min.mjs`），
  而该路径被 Vite 注入了 `import { injectQuery } from "/@vite/client"` 作为 ES module 第一行。
  PDF.js 通过 `new Worker(url, { type: 'module' })` 加载时，Worker 内部尝试解析
  `"/@vite/client"` 相对路径变成 `/node_modules/pdfjs-dist/build/@vite/client` → 404
  → Worker 加载失败 → 控制台报 `Worker was unable to load ...`，PDF 一直转圈。

修复方案：
  - worker 文件由 postinstall 钩子从 node_modules 拷贝到 public/，路径固定为 `/pdf.worker.min.mjs`
  - Vite dev 直接服务 public/（无 HMR 注入），vite build 把 public/ 复制到 dist/
  - FastAPI 静态托管 dist/ 也直接服务该路径

本脚本 4 类断言：
  1. public/pdf.worker.min.mjs 存在且非空（postinstall 已跑过）
  2. PDFViewer 源码不再 import `pdfjs-dist/build/pdf.worker.min.mjs?url`
  3. PDFViewer 源码用常量 `/pdf.worker.min.mjs`
  4. package.json 配了 postinstall 钩子调用 copy-pdf-worker.mjs
  5. scripts/copy-pdf-worker.mjs 存在并真的拷贝
  6. dist/pdf.worker.min.mjs 存在（生产构建复制了 public/）
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


def _expect(label: str, ok: bool, detail: str = "") -> bool:
    flag = "PASS" if ok else "FAIL"
    line = f"[{flag}] {label}"
    if detail:
        line += f"  — {detail}"
    print(line)
    return ok


def check_public_worker() -> bool:
    p = FRONTEND / "public" / "pdf.worker.min.mjs"
    ok = p.exists() and p.stat().st_size > 100_000
    return _expect(
        "public/pdf.worker.min.mjs 存在且非空（postinstall 钩子产物）",
        ok,
        f"path={p} size={p.stat().st_size if p.exists() else 0}",
    )


def check_pdfviewer_no_qmark_url() -> bool:
    src = (FRONTEND / "src" / "components" / "ui" / "pdf-viewer.tsx").read_text(
        encoding="utf-8"
    )
    bad_pattern = re.search(
        r"import\s+\w+\s+from\s+['\"]pdfjs-dist/build/pdf\.worker[^\"']*\?url['\"]",
        src,
    )
    return _expect(
        "PDFViewer 不再 import 'pdfjs-dist/build/pdf.worker.min.mjs?url'",
        bad_pattern is None,
        "已切换到 /pdf.worker.min.mjs 常量（避免 vite HMR 注入破坏 Worker）",
    )


def check_pdfviewer_uses_public_url() -> bool:
    src = (FRONTEND / "src" / "components" / "ui" / "pdf-viewer.tsx").read_text(
        encoding="utf-8"
    )
    has_const = "WORKER_SRC" in src and "/pdf.worker.min.mjs" in src
    has_assignment = re.search(
        r"pdfjs\.GlobalWorkerOptions\.workerSrc\s*=\s*WORKER_SRC",
        src,
    )
    return _expect(
        "PDFViewer 设置 workerSrc = '/pdf.worker.min.mjs'",
        has_const and has_assignment is not None,
    )


def check_no_options_unstable_prop() -> bool:
    """options={{}} 每次 render 创建新对象 → 触发 'Options prop changed' warning
    → 不必要的 worker reload。修复方案是不传 options（或 useMemo 稳定的对象）。"""
    src = (FRONTEND / "src" / "components" / "ui" / "pdf-viewer.tsx").read_text(
        encoding="utf-8"
    )
    bad = re.search(r"options\s*=\s*\{\{", src)
    return _expect(
        "PDFViewer 不传内联 options={{}}（避免 worker 不必要 reload）",
        bad is None,
    )


def check_postinstall_script() -> bool:
    pkg = (FRONTEND / "package.json").read_text(encoding="utf-8")
    has = '"postinstall"' in pkg and "copy-pdf-worker.mjs" in pkg
    return _expect(
        "package.json 注册 postinstall → scripts/copy-pdf-worker.mjs",
        has,
    )


def check_copy_script_exists() -> bool:
    p = FRONTEND / "scripts" / "copy-pdf-worker.mjs"
    if not p.exists():
        return _expect("scripts/copy-pdf-worker.mjs 存在", False, f"missing: {p}")
    src = p.read_text(encoding="utf-8")
    imports_pdfjs = "pdfjs-dist/build/pdf.worker.min.mjs" in src
    copies_to_public = "public/pdf.worker.min.mjs" in src
    return _expect(
        "scripts/copy-pdf-worker.mjs 拷贝 node_modules/pdfjs-dist → public/",
        imports_pdfjs and copies_to_public,
    )


def check_dist_after_build() -> bool:
    """如果 dist/ 不存在（如 dev-only 环境），跳过；存在则必须含 worker。"""
    p = FRONTEND / "dist" / "pdf.worker.min.mjs"
    if not p.exists():
        return _expect(
            "dist/pdf.worker.min.mjs 存在（生产构建产物）",
            True,
            "skip（dist/ 不存在，未运行 npm run build）",
        )
    ok = p.stat().st_size > 100_000
    return _expect(
        "dist/pdf.worker.min.mjs 存在且非空",
        ok,
        f"size={p.stat().st_size}",
    )


def main() -> int:
    print("=== qa_verify_pdf_worker_dev ===\n")
    results = [
        check_public_worker(),
        check_pdfviewer_no_qmark_url(),
        check_pdfviewer_uses_public_url(),
        check_no_options_unstable_prop(),
        check_postinstall_script(),
        check_copy_script_exists(),
        check_dist_after_build(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())