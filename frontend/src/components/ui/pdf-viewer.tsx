import { useState, useCallback, useRef, useEffect } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import { Button } from './button'
import { ZoomIn, ZoomOut, Download, X } from 'lucide-react'
import { cn } from '@/utils'
// ─── react-pdf 10.x 必须显式导入这两个 CSS ────────────────────────────────
// 不导入的话控制台会刷屏：`TextLayer styles not found` + `AnnotationLayer styles not found`
// 因为 react-pdf 把 TextLayer 的样式从 inline style 拆到 CSS 文件里。
import 'react-pdf/dist/Page/TextLayer.css'
import 'react-pdf/dist/Page/AnnotationLayer.css'

// 本地打包 worker：通过 npm postinstall 钩子把 node_modules/pdfjs-dist/build/pdf.worker.min.mjs
// 复制到 public/ 下，开发态走 /pdf.worker.min.mjs（Vite 不注入 HMR client，避免 Worker 加载失败）。
// 生产态 dist/ 已包含同样的 public/ 文件，FastAPI 静态托管可直接服务该 URL。
// 选用 public/ 而非 `?url` 是因为后者在 dev 模式下会被注入 `import { injectQuery } from "/@vite/client"`，
// Web Worker 加载时该相对路径解析错误导致 404，进而 PDF.js 报 `Worker was unable to load`。
const WORKER_SRC = '/pdf.worker.min.mjs'

// 设置 PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = WORKER_SRC

interface PDFViewerProps {
  url: string
  className?: string
  onClose?: () => void
}

export function PDFViewer({ url, className, onClose }: PDFViewerProps) {
  const [numPages, setNumPages] = useState<number | null>(null)
  const [scale, setScale] = useState<number>(1.0)
  const [error, setError] = useState<string | null>(null)
  const [jumpTo, setJumpTo] = useState<string>('')  // "跳到第 N 页" 输入
  // 当前可视页（IntersectionObserver 探测）：用于工具栏显示 "1 / 17" 之类的当前位置提示。
  // 连续滚动模式下传统 pageNumber 不再合适，所以用「最近一次滚到视口里的页号」表示当前页。
  const [currentVisiblePage, setCurrentVisiblePage] = useState<number>(1)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map())

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setNumPages(numPages)
    setError(null)
  }, [])

  const onDocumentLoadError = useCallback((err: Error) => {
    setError('PDF 加载失败: ' + err.message)
  }, [])

  const zoomIn = () => {
    setScale((prev) => Math.min(prev + 0.2, 3.0))
  }

  const zoomOut = () => {
    setScale((prev) => Math.max(prev - 0.2, 0.5))
  }

  const handleDownload = () => {
    const link = document.createElement('a')
    link.href = url
    link.download = 'paper.pdf'
    link.target = '_blank'
    link.click()
  }

  // "跳到第 N 页"：输入框回车后，把对应 pageRef 滚到视口顶部
  const handleJumpSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const target = parseInt(jumpTo, 10)
    if (Number.isNaN(target) || target < 1 || target > (numPages ?? 1)) {
      setJumpTo('')
      return
    }
    const el = pageRefs.current.get(target)
    if (el && scrollRef.current) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      setJumpTo('')
    }
  }

  // Ctrl+滚轮缩放 PDF（接管浏览器的页面缩放）。
  // 必须用原生 addEventListener + { passive: false }：React 的 onWheel JSX 属性
  // 在 Chrome 下挂在 document root 且默认 passive，preventDefault() 会无效。
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return  // 普通滚轮 = 正常滚动，不干预
      e.preventDefault()                      // 阻止浏览器页面缩放
      // deltaY < 0 = 放大；> 0 = 缩小。步长 0.1，比按钮的 0.2 更细腻（滚轮是连续操作）
      setScale((prev) => {
        const next = prev + (e.deltaY < 0 ? 0.1 : -0.1)
        return Math.min(Math.max(next, 0.5), 3.0)
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // 连续滚动模式下追踪「当前可视页」——监听每个 <Page> 容器进入/离开视口，
  // 选 scrollRoot 内距顶部最近且 ≥ 0 的页号作为 currentVisiblePage。
  useEffect(() => {
    if (numPages === null) return
    const observer = new IntersectionObserver(
      (entries) => {
        // entries 里按 intersectionRatio 选最大可见比例的
        let bestRatio = 0
        let bestPage = currentVisiblePage
        for (const entry of entries) {
          const pageNum = Number(entry.target.getAttribute('data-page-number'))
          if (Number.isNaN(pageNum)) continue
          if (entry.isIntersecting && entry.intersectionRatio > bestRatio) {
            bestRatio = entry.intersectionRatio
            bestPage = pageNum
          }
        }
        if (bestRatio > 0 && bestPage !== currentVisiblePage) {
          setCurrentVisiblePage(bestPage)
        }
      },
      {
        root: scrollRef.current,
        // 只要页面顶部进入视口就算「可视」
        rootMargin: '0px 0px -80% 0px',
        threshold: [0, 0.25, 0.5, 0.75, 1],
      },
    )
    pageRefs.current.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [numPages, currentVisiblePage])

  const pdfSpinner = (
    <div className="flex items-center justify-center h-96">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
    </div>
  )

  const pdfError = (
    <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
      <p className="text-red-500 mb-2">{error || 'PDF 加载失败'}</p>
      <Button variant="outline" onClick={handleDownload}>
        <Download className="w-4 h-4 mr-2" />
        下载 PDF
      </Button>
    </div>
  )

  return (
    <div className={cn('flex flex-col h-full bg-background rounded-lg border', className)}>
      {/* 工具栏 */}
      <div className="flex items-center justify-between p-3 border-b bg-muted/30 gap-2">
        <div className="flex items-center gap-2">
          {/* 当前可视页提示（连续滚动模式下的「当前位置」标记） */}
          <span className="text-sm min-w-[80px] text-center font-mono">
            {currentVisiblePage} / {numPages ?? '—'}
          </span>
          {/* 跳到指定页：连续滚动场景下保留这个比左右翻页按钮更高效的工具 */}
          <form onSubmit={handleJumpSubmit} className="flex items-center gap-1">
            <input
              type="number"
              min={1}
              max={numPages ?? undefined}
              value={jumpTo}
              onChange={(e) => setJumpTo(e.target.value)}
              placeholder="跳到…"
              className="w-16 h-8 px-2 text-sm border rounded bg-background"
            />
            <Button type="submit" variant="outline" size="sm" disabled={numPages === null}>
              GO
            </Button>
          </form>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={zoomOut}>
            <ZoomOut className="w-4 h-4" />
          </Button>
          <span className="text-sm min-w-[60px] text-center">{Math.round(scale * 100)}%</span>
          <Button variant="ghost" size="sm" onClick={zoomIn}>
            <ZoomIn className="w-4 h-4" />
          </Button>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={handleDownload}>
            <Download className="w-4 h-4" />
          </Button>
          {onClose && (
            <Button variant="ghost" size="sm" onClick={onClose}>
              <X className="w-4 h-4" />
            </Button>
          )}
        </div>
      </div>

      {/* PDF 内容：连续滚动模式——自实现 <Pages>（react-pdf 10.x 没原生 Pages 组件） */}
      <div ref={scrollRef} className="flex-1 overflow-auto p-4">
        <Document
          file={url}
          onLoadSuccess={onDocumentLoadSuccess}
          onLoadError={onDocumentLoadError}
          loading={pdfSpinner}
          error={pdfError}
        >
          {numPages !== null && (
            <div className="flex flex-col items-center gap-4">
              {Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => (
                <div
                  key={pageNum}
                  data-page-number={pageNum}
                  ref={(el) => {
                    if (el) pageRefs.current.set(pageNum, el)
                    else pageRefs.current.delete(pageNum)
                  }}
                  className="shadow-lg"
                >
                  <Page
                    pageNumber={pageNum}
                    scale={scale}
                    renderTextLayer={true}
                    renderAnnotationLayer={true}
                  />
                </div>
              ))}
            </div>
          )}
        </Document>
      </div>
    </div>
  )
}

// PDF 预览对话框
interface PDFPreviewDialogProps {
  isOpen: boolean
  url: string
  title?: string
  onClose: () => void
}

export function PDFPreviewDialog({ isOpen, url, title, onClose }: PDFPreviewDialogProps) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="w-full max-w-5xl h-[90vh] flex flex-col bg-background rounded-lg shadow-2xl overflow-hidden">
        {title && (
          <div className="flex items-center justify-between p-4 border-b shrink-0">
            <h3 className="font-semibold truncate flex-1">{title}</h3>
            <Button variant="ghost" size="sm" onClick={onClose}>
              <X className="w-4 h-4" />
            </Button>
          </div>
        )}
        <div className="flex-1 min-h-0">
          <PDFViewer url={url} onClose={onClose} />
        </div>
      </div>
    </div>
  )
}
