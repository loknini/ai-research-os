"""QA 验证：PDFViewer 组件在 PaperHub 预览链路上的契约正确性。

本脚本盯前端源码层契约（后端 GET /api/papers/{arxiv_id}/pdf 路由
在 qa_verify_paper_pdf_stream.py 里覆盖，这里不复测）。

累计覆盖历史修复（按时间倒序）：
  2026-08-26 (5): 弹窗改 flex 布局，scrollbar 不再越出对话框底边
  2026-08-26 (4): Ctrl+滚轮缩放 PDF（接管浏览器页面缩放）
  2026-08-26 (3): react-pdf 10.x CSS 缺失导致控制台两条 warning 刷屏
  2026-08-26 (3): 只能单页翻 → 改成连续滚动（自实现 <Pages>）
  2026-08-26 (2): Vite dev 模式 worker 加载失败（改用 public/ 静态资源，由 worker QA 覆盖）
  2026-08-26 (1): `<Document>` 被 `!loading` 条件渲染挡住 → 死循环

跑法：python scripts/qa_verify_pdf_viewer_render.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PDF_VIEWER = ROOT / "frontend" / "src" / "components" / "ui" / "pdf-viewer.tsx"
PAPER_HUB = ROOT / "frontend" / "src" / "hubs" / "paper" / "PaperHub.tsx"
PAPER_CARD = ROOT / "frontend" / "src" / "components" / "paper" / "paper-card.tsx"


def _read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"❌ 文件不存在: {p}")
    return p.read_text(encoding="utf-8")


def _expect(name: str, ok: bool, detail: str = "") -> bool:
    icon = "✅" if ok else "❌"
    suffix = f" — {detail}" if detail else ""
    print(f"   {icon} {name}{suffix}")
    return ok


def check_pdf_viewer_no_deadloop() -> bool:
    print("\n[1/3] PDFViewer 源码层断言（不死循环 + 用 Document 内置 props）")
    src = _read(PDF_VIEWER)
    results: list[bool] = []

    # 1. 禁止出现 `{!loading && ...}` 这种把 Document 挡在外面的条件渲染
    bad_pattern = re.compile(r"\{!loading\s*&&")
    has_deadloop = bad_pattern.search(src) is not None
    results.append(_expect(
        "无 `{!loading && ...}` 死循环条件渲染（Document 不再被挡在外面）",
        not has_deadloop,
        "仍存在 — Document 永不被渲染" if has_deadloop else "",
    ))

    # 2. Document 必须使用内置 loading prop（react-pdf 标准用法）
    has_loading_prop = re.search(
        r"<Document\b[^>]*\bloading\s*=", src, flags=re.DOTALL
    ) is not None
    results.append(_expect(
        "Document 使用内置 `loading=` prop（react-pdf 标准用法）",
        has_loading_prop,
    ))

    # 3. Document 必须有 onLoadSuccess（触发 numPages 更新）
    has_on_load_success = re.search(
        r"<Document\b[^>]*\bonLoadSuccess\s*=", src, flags=re.DOTALL
    ) is not None
    results.append(_expect(
        "Document 有 `onLoadSuccess` 回调",
        has_on_load_success,
    ))

    # 4. Document 必须有 onLoadError（PDF 解析失败时显示错误 UI）
    has_on_load_error = re.search(
        r"<Document\b[^>]*\bonLoadError\s*=", src, flags=re.DOTALL
    ) is not None
    results.append(_expect(
        "Document 有 `onLoadError` 回调",
        has_on_load_error,
    ))

    # 5. Document 必须把错误 UI 通过内置 error prop 传入（加载失败时显示）
    has_error_prop = re.search(
        r"<Document\b[^>]*\berror\s*=", src, flags=re.DOTALL
    ) is not None
    results.append(_expect(
        "Document 使用内置 `error=` prop（加载失败显示错误 + 下载按钮）",
        has_error_prop,
    ))

    # 6. 仍然使用本地打包的 pdf.worker（避免 cdnjs 离线失败）
    has_local_worker = "pdfjs-dist/build/pdf.worker" in src
    results.append(_expect(
        "使用本地 pdfjs-dist worker（无外网 CDN 依赖）",
        has_local_worker,
    ))

    # 7. numPages 状态用 `number | null` 区分「加载中」与「已加载」
    uses_nullable_numpages = re.search(
        r"useState<number\s*\|\s*null>", src
    ) is not None
    results.append(_expect(
        "numPages 用 `number | null` 区分「加载中」与「已加载」",
        uses_nullable_numpages,
    ))

    # 8. toolbar 不再展示「1 / 0」（0 是「加载中」与「0 页 PDF」的歧义状态）
    # 连续滚动模式下用 currentVisiblePage 显示当前位置，加载中也显示「—」。
    toolbar_shows_dash = re.search(
        r"\{currentVisiblePage\}\s*/\s*\{numPages\s*\?\?\s*['\"]—['\"]\}", src
    ) is not None
    results.append(_expect(
        "toolbar 加载中显示 `1 / —`（不再有 `1 / 0` 歧义）",
        toolbar_shows_dash,
    ))

    # ── 2026-08-26 (3) 修复：导入 TextLayer.css + AnnotationLayer.css ──────────
    has_text_layer_css = "react-pdf/dist/Page/TextLayer.css" in src
    results.append(_expect(
        "导入 react-pdf TextLayer.css（消除 `TextLayer styles not found` warning）",
        has_text_layer_css,
    ))
    has_annotation_layer_css = "react-pdf/dist/Page/AnnotationLayer.css" in src
    results.append(_expect(
        "导入 react-pdf AnnotationLayer.css（消除 `AnnotationLayer styles not found` warning）",
        has_annotation_layer_css,
    ))

    # ── 2026-08-26 (3) 修复：连续滚动（自实现 <Pages>） ───────────────────────
    uses_array_from_pages = re.search(
        r"Array\.from\(\s*\{\s*length:\s*numPages\s*\}", src
    ) is not None
    results.append(_expect(
        "PDFViewer 用 Array.from 循环渲染多页（连续滚动模式）",
        uses_array_from_pages,
    ))
    # 单页模式标记已删除：源文件里不再有 `pageNumber={pageNumber}` 这种硬绑定的单页用法
    has_single_page_binding = re.search(
        r"pageNumber=\{pageNumber\}", src
    ) is not None
    results.append(_expect(
        "PDFViewer 没有 `pageNumber={pageNumber}` 单页硬绑定（已切连续滚动）",
        not has_single_page_binding,
        "仍存在单页硬绑定" if has_single_page_binding else "",
    ))
    # 工具栏不应再有 ChevronLeft / ChevronRight 按钮（连续滚动不需要左右翻页）
    no_prev_next_chevrons = (
        "ChevronLeft" not in src and "ChevronRight" not in src
    )
    results.append(_expect(
        "工具栏不再用 ChevronLeft / ChevronRight（连续滚动不需要）",
        no_prev_next_chevrons,
    ))

    # ── 2026-08-26 (4) 修复：Ctrl+滚轮缩放接管浏览器页面缩放 ────────────────
    # 必须是原生 addEventListener + { passive: false }（React onWheel 在 Chrome
    # 下默认 passive，preventDefault 无效，浏览器照样缩放页面）
    has_native_wheel_listener = re.search(
        r"addEventListener\(\s*['\"]wheel['\"]\s*,\s*\w+\s*,\s*\{\s*passive:\s*false\s*\}\s*\)",
        src,
    ) is not None
    results.append(_expect(
        "原生 `addEventListener('wheel', ..., { passive: false })`（preventDefault 才有效）",
        has_native_wheel_listener,
        "缺失 — React onWheel 默认 passive，Ctrl+滚轮仍会触发浏览器页面缩放" if not has_native_wheel_listener else "",
    ))
    # Ctrl / ⌘ + 滚轮时必须 preventDefault（阻止浏览器缩放）并更新 scale
    ctrl_wheel_handles_zoom = (
        re.search(r"e\.ctrlKey\s*\|\|\s*e\.metaKey", src) is not None
        and re.search(r"e\.preventDefault\(\)", src) is not None
        and re.search(r"deltaY\s*<\s*0", src) is not None
    )
    results.append(_expect(
        "Ctrl/⌘ + 滚轮 → preventDefault + deltaY 方向判断 + 更新 scale",
        ctrl_wheel_handles_zoom,
    ))
    # 普通滚轮（无 Ctrl）不能被拦截，否则连续滚动失效
    plain_wheel_passes_through = re.search(
        r"if\s*\(\s*!\s*\(\s*e\.ctrlKey\s*\|\|\s*e\.metaKey\s*\)\s*\)\s*return", src
    ) is not None
    results.append(_expect(
        "普通滚轮（无 Ctrl）直接 return 不拦截（连续滚动不受影响）",
        plain_wheel_passes_through,
    ))

    return all(results)


def check_paperhub_preview_url() -> bool:
    print("\n[2/3] PaperHub 接入层断言（指向正确 URL）")
    src = _read(PAPER_HUB)
    results: list[bool] = []

    # 1. url 模板里包含 `/pdf` 后缀
    url_with_pdf = re.search(
        r"url:\s*`/api/papers/\$\{[^}]+\}/pdf`",
        src,
    ) is not None
    results.append(_expect(
        "PaperHub.onPreviewPDF 把 url 设为 `/api/papers/{arxivId}/pdf`",
        url_with_pdf,
    ))

    # 2. PaperHub 调 PDFPreviewDialog
    uses_dialog = "PDFPreviewDialog" in src
    results.append(_expect(
        "PaperHub 使用 PDFPreviewDialog 弹窗",
        uses_dialog,
    ))

    # 3. 旧 dead code：onPreviewPDF handler 里不应有 `paper.localPath &&` 这种守卫
    # （之前的 bug：localPath 为空时按钮存在但 onClick 是死代码）。注释里提"paper.localPath"
    # 是为了说明为什么去掉守卫的，不算违规——只看真实守卫模式 `paper.localPath &&` / `if (paper.localPath)`。
    localpath_guard_in_hub = re.search(
        r"(paper\.localPath\s*&&|if\s*\(\s*paper\.localPath\s*\))",
        src,
    ) is not None
    results.append(_expect(
        "PaperHub.onPreviewPDF 无 `paper.localPath &&` / `if (paper.localPath)` 守卫",
        not localpath_guard_in_hub,
        "真实守卫仍存在 — localPath 为空时无法触发预览" if localpath_guard_in_hub else "",
    ))

    return all(results)


def check_papercard_no_localpath_guard() -> bool:
    print("\n[3/3] PaperCard「查看」按钮无 localPath 守卫")
    src = _read(PAPER_CARD)
    # 检查「查看」按钮（onPreviewPDF）的渲染条件里没有 paper.localPath
    # 正确写法是 `{onPreviewPDF && (<Button ... onClick={onPreviewPDF}>...查看...</Button>)}`
    no_localpath_guard = re.search(
        r"\{onPreviewPDF\s*&&\s*\(\s*<Button[^>]*onClick=\{onPreviewPDF\}",
        src,
        flags=re.DOTALL,
    ) is not None
    # 同时确认代码里不再有 paper.localPath 守卫（防止新引入）
    has_localpath_anywhere_in_preview = re.search(
        r"onPreviewPDF[^\n]*paper\.localPath",
        src,
    ) is not None
    results = [
        _expect(
            "PaperCard 查看按钮无 `paper.localPath` 守卫",
            no_localpath_guard and not has_localpath_anywhere_in_preview,
            "守卫存在 — localPath 为空时按钮不会显示" if has_localpath_anywhere_in_preview else "",
        ),
    ]
    return all(results)


def check_pdf_dialog_flex_layout() -> bool:
    """回归弹窗 flex 布局——保证 title bar 与 PDFViewer 兄弟节点不重叠，scrollbar 不越界。

    旧 bug：弹窗外层只设 h-[90vh] overflow-hidden，子节点 title + `h-full` 内层 div
    都是普通 block，`h-full` = 父容器 100% 高度（90vh）但没有扣掉 title 高度，所以
    PDFViewer 整体高出 title 高度，底部超出对话框，scrollbar 被画到对话框下边界之外。
    修法：弹窗改 `flex flex-col`、title 加 `shrink-0`、内层 `flex-1 min-h-0`。
    `min-h-0` 不可省——flex 子项默认 min-height: auto，overflow-auto 不会触发。
    """
    print("\n[4/4] PDFPreviewDialog 弹窗 flex 布局（scrollbar 不越界）")
    src = _read(PDF_VIEWER)
    results: list[bool] = []

    # 1. 弹窗外层必须是 flex flex-col
    dialog_uses_flex = re.search(
        r"max-w-5xl[^>]*h-\[90vh\][^>]*flex\s+flex-col", src
    ) is not None
    results.append(_expect(
        "弹窗外层 `flex flex-col`（title + 内层 才能正确瓜分高度）",
        dialog_uses_flex,
        "仍是非 flex 布局 — `h-full` 子节点不会扣掉 title 高度，scrollbar 会越界"
        if not dialog_uses_flex else "",
    ))

    # 2. title bar 必须 shrink-0（不被压缩）
    title_shrink_zero = re.search(
        r"border-b[^>]*shrink-0", src
    ) is not None
    results.append(_expect(
        "title bar `shrink-0`（不被 PDFViewer 挤掉高度）",
        title_shrink_zero,
    ))

    # 3. 内层 wrapper 必须 `flex-1 min-h-0`（关键：min-h-0 让 overflow-auto 真正生效）
    inner_uses_flex_min_h = re.search(
        r"flex-1\s+min-h-0", src
    ) is not None
    results.append(_expect(
        "内层 wrapper `flex-1 min-h-0`（min-h-0 是 flex 子项 + overflow-auto 生效的前提）",
        inner_uses_flex_min_h,
        "缺 min-h-0 时 flex 子项默认 min-height: auto，overflow-auto 不会真正触发滚动"
        if not inner_uses_flex_min_h else "",
    ))

    return all(results)


def main() -> int:
    print("🔍 PDFViewer 死循环 bug 回归测试")
    print("=" * 60)

    a = check_pdf_viewer_no_deadloop()
    b = check_paperhub_preview_url()
    c = check_papercard_no_localpath_guard()
    d = check_pdf_dialog_flex_layout()

    print("\n" + "=" * 60)
    if a and b and c and d:
        print("✅ ALL_PASS")
        return 0
    else:
        print("❌ FAIL")
        return 1


if __name__ == "__main__":
    sys.exit(main())