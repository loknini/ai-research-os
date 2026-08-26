/**
 * Paper Hub 容器组件。
 * 原 monolith index.tsx 拆分后的组合根：保留全部 useState / useEffect、
 * 业务 handler（store 更新 + toast + 调 service）与 JSX 装配。
 * 派生状态与批量操作下沉到 hooks/usePaperData，API 下沉到 services/papersApi，
 * 筛选面板与抓取对话框下沉到 components/。
 */

import { useState, useEffect, useCallback } from 'react'
import { useAppStore } from '@/stores/appStore'
import { Header, HeaderAction } from '@/components/layout/header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useToast } from '@/components/ui/toast'
import { cn } from '@/utils'
import CitationHub from '@/hubs/citation'
import { PaperListSkeleton } from '@/components/ui/skeleton'
import { PaperCard } from '@/components/paper/paper-card'
import { PDFPreviewDialog } from '@/components/ui/pdf-viewer'
import {
  Search,
  Plus,
  Star,
  CheckCircle,
  FileText,
  RefreshCw,
  EyeOff,
  Trash2,
  Tag,
  Filter,
  ChevronLeft,
  ChevronRight,
  X
} from 'lucide-react'
import type { Paper } from '@/types'
import type { SortOption, FilterOption } from './types'
import {
  loadLocalPapers,
  fetchPapers,
  summarizePaper,
  downloadPaperPDF,
  deletePaperApi
} from './services/papersApi'
import { usePaperData } from './hooks/usePaperData'
import PaperFilters from './components/PaperFilters'
import FetchPapersTab, { type FetchBatchResult } from './components/FetchPapersTab'

export default function PaperHub() {
  const { papers, setPapers, updatePaper, deletePaper, isLoadingPapers, setLoadingPapers, isConnected } = useAppStore()
  const { showToast, ToastContainer } = useToast()
  // 工具 Tab：论文管理 / 抓取论文 / 引用生成（后者收纳为论文中心子能力）
  const [activeTool, setActiveTool] = useState<'papers' | 'fetch' | 'citation'>('papers')
  const [searchQuery, setSearchQuery] = useState('')
  const [isFetching, setIsFetching] = useState(false)
  // 最近一次抓取结果（供「抓取论文」Tab 实时预览）
  const [lastFetchResult, setLastFetchResult] = useState<FetchBatchResult | null>(null)
  // 存储已展开的论文ID和完整摘要
  const [expandedAbstracts, setExpandedAbstracts] = useState<Map<string, string>>(new Map())

  // 筛选和排序状态
  const [filterOption, setFilterOption] = useState<FilterOption>('all')
  const [sortOption, setSortOption] = useState<SortOption>('date-desc')
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [showFilters, setShowFilters] = useState(false)

  // 确认对话框状态
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean
    paperId: string
    title: string
  }>({ isOpen: false, paperId: '', title: '' })

  // 批量操作状态
  const [selectedPapers, setSelectedPapers] = useState<Set<string>>(new Set())
  const [isBatchMode, setIsBatchMode] = useState(false)
  const [batchTagInput, setBatchTagInput] = useState('')
  const [showBatchTagInput, setShowBatchTagInput] = useState(false)

  // 分页状态
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)

  // PDF 预览状态
  const [pdfPreview, setPdfPreview] = useState<{
    isOpen: boolean
    url: string
    title: string
  }>({ isOpen: false, url: '', title: '' })

  // 生成 BibTeX 弹窗状态（引用的论文 id；null = 关闭）
  const [bibtexPaperId, setBibtexPaperId] = useState<string | null>(null)
  const bibtexPaper = papers.find((p) => p.id === bibtexPaperId) || null

  // 保存 BibTeX 到论文
  const handleSaveBibtex = useCallback(
    async (paperId: string, bibtex: string) => {
      try {
        const response = await fetch(`/api/papers/${paperId}/bibtex`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bibtex }),
        })
        const data = await response.json()
        if (data.success) {
          // 同步更新本地 store
          const paper = papers.find((p) => p.id === paperId)
          if (paper) updatePaper(paperId, { bibtex })
          setBibtexPaperId(null)
          showToast('BibTeX 已保存到论文', 'success')
        } else {
          showToast(data.message || '保存失败', 'error')
        }
      } catch (error) {
        console.error('Save bibtex error:', error)
        showToast('保存失败', 'error')
      }
    },
    [papers, updatePaper, showToast]
  )

  const loadLocalPapersData = useCallback(async () => {
    setLoadingPapers(true)
    try {
      const localPapers = await loadLocalPapers()
      setPapers(localPapers)
    } catch (error) {
      console.error('Failed to load papers:', error)
      setPapers([])
    } finally {
      setLoadingPapers(false)
    }
  }, [setLoadingPapers, setPapers])

  // 加载本地论文
  useEffect(() => {
    void loadLocalPapersData()
  }, [loadLocalPapersData])

  const handleFetchPapers = async (params?: { keywords: string; maxResults: number }) => {
    const keywords = params?.keywords ?? ''
    const maxResults = params?.maxResults ?? 10
    setIsFetching(true)
    showToast('正在抓取论文...', 'info')

    try {
      // 调用后端 API 执行 Python 脚本
      const result = await fetchPapers({ keywords, maxResults })

      const newCount = result.papers.length || 0
      const totalCount = result.total || 0
      const insertedCount = (result as { inserted?: number }).inserted ?? newCount
      if (newCount > 0) {
        showToast(
          `本次抓取 ${newCount} 篇，新增 ${insertedCount} 篇，当前共 ${totalCount} 篇`,
          'success'
        )
      } else {
        showToast(`没有发现新论文，当前共 ${totalCount} 篇（已跳过重复）`, 'info')
      }
      // 更新本次抓取结果预览（抓取论文 Tab 渲染用）
      setLastFetchResult({
        papers: result.papers,
        total: totalCount,
        inserted: insertedCount,
        fetchedAt: Date.now(),
        keywords,
        maxResults,
      })
      // 重新加载论文管理列表
      await loadLocalPapersData()
    } catch (error) {
      console.error('Fetch error:', error)
      showToast('抓取失败，请检查网络连接', 'error')
    } finally {
      setIsFetching(false)
    }
  }

  const [summarizingIds, setSummarizingIds] = useState<Set<string>>(new Set())

  const handleSummarize = async (paper: Paper) => {
    if (summarizingIds.has(paper.id)) return

    setSummarizingIds((prev) => new Set(prev).add(paper.id))
    showToast(`正在生成 "${paper.title.substring(0, 30)}..." 的总结...`, 'info')

    try {
      const result = await summarizePaper(paper.id)
      if (result.success) {
        // 更新本地论文数据
        updatePaper(paper.id, { summary: result.summary })
        showToast(`总结生成完成: "${paper.title.substring(0, 30)}..."`, 'success')
      } else {
        showToast(`总结生成失败: ${result.message}`, 'error')
      }
    } catch (error) {
      console.error('Summarize error:', error)
      showToast('总结生成失败，请检查网络连接', 'error')
    } finally {
      setSummarizingIds((prev) => {
        const newSet = new Set(prev)
        newSet.delete(paper.id)
        return newSet
      })
    }
  }

  const handleDownloadPDF = async (arxivId: string, title: string) => {
    try {
      showToast(`正在下载 PDF: ${title.substring(0, 30)}...`, 'info')

      const result = await downloadPaperPDF(arxivId)
      if (result.success) {
        showToast('PDF 下载完成', 'success')
        // 更新论文的localPath
        const paper = papers.find((p) => p.arxivId === arxivId)
        if (paper) {
          updatePaper(paper.id, { localPath: result.path })
        }
      } else {
        showToast(`下载失败: ${result.message}`, 'error')
      }
    } catch (error) {
      console.error('Download error:', error)
      showToast('PDF 下载失败', 'error')
    }
  }

  const toggleRead = (id: string, current: boolean) => {
    updatePaper(id, { isRead: !current })
  }

  const toggleFavorite = (id: string, current: boolean) => {
    updatePaper(id, { isFavorite: !current })
  }

  const handleExpandAbstract = (paper: Paper) => {
    // 如果已经展开，则收起
    if (expandedAbstracts.has(paper.id)) {
      setExpandedAbstracts((prev) => {
        const newMap = new Map(prev)
        newMap.delete(paper.id)
        return newMap
      })
    } else {
      // 展开：使用完整摘要（本地已有）
      setExpandedAbstracts((prev) => {
        const newMap = new Map(prev)
        newMap.set(paper.id, paper.abstract)
        return newMap
      })
    }
  }

  const showDeleteConfirm = (id: string, title: string) => {
    setConfirmDialog({
      isOpen: true,
      paperId: id,
      title
    })
  }

  const handleDeletePaper = async () => {
    const { paperId, title } = confirmDialog

    try {
      const ok = await deletePaperApi(paperId)
      if (ok) {
        // 从本地状态中移除
        deletePaper(paperId)
        showToast(`已删除 "${title.substring(0, 30)}..."`, 'success')
      } else {
        showToast('删除失败', 'error')
      }
    } catch (error) {
      console.error('Delete error:', error)
      showToast('删除失败', 'error')
    } finally {
      setConfirmDialog((prev) => ({ ...prev, isOpen: false }))
    }
  }

  // 派生状态 + 批量操作（来自 hooks/usePaperData）
  const {
    allTags,
    filteredPapers,
    totalPages,
    paginatedPapers,
    toggleTagFilter,
    togglePaperSelection,
    toggleSelectAll,
    clearSelection,
    handleBatchDelete,
    handleBatchMarkRead,
    handleBatchAddTags,
    handleBatchFavorite
  } = usePaperData({
    papers,
    searchQuery,
    filterOption,
    sortOption,
    selectedTags,
    setSelectedTags,
    currentPage,
    setCurrentPage,
    pageSize,
    selectedPapers,
    setSelectedPapers,
    setIsBatchMode,
    batchTagInput,
    setBatchTagInput,
    setShowBatchTagInput,
    updatePaper,
    deletePaper,
    showToast
  })

  return (
    <div className="flex flex-col h-screen">
      <Header
        title="论文中心"
        description="管理你的学术论文收藏"
        actions={
          <HeaderAction
            icon={isFetching ? RefreshCw : Plus}
            label={isFetching ? '抓取中...' : '抓取论文'}
            onClick={() => setActiveTool('fetch')}
          />
        }
      />

      {/* 工具 Tab：抓取论文/引用工具已收纳为论文中心的子能力，/citation 路由仍保留可直达 */}
      <div className="px-6 pt-3 flex items-center gap-1 border-b border-border/60">
        <button
          className={cn(
            'px-4 py-2 text-sm font-medium transition-colors',
            activeTool === 'papers'
              ? 'text-primary border-b-2 border-primary'
              : 'text-muted-foreground hover:text-foreground'
          )}
          onClick={() => setActiveTool('papers')}
        >
          论文管理
        </button>
        <button
          className={cn(
            'px-4 py-2 text-sm font-medium transition-colors',
            activeTool === 'fetch'
              ? 'text-primary border-b-2 border-primary'
              : 'text-muted-foreground hover:text-foreground'
          )}
          onClick={() => setActiveTool('fetch')}
        >
          抓取论文
        </button>
        <button
          className={cn(
            'px-4 py-2 text-sm font-medium transition-colors',
            activeTool === 'citation'
              ? 'text-primary border-b-2 border-primary'
              : 'text-muted-foreground hover:text-foreground'
          )}
          onClick={() => setActiveTool('citation')}
        >
          引用工具
        </button>
      </div>

      {activeTool === 'papers' ? (
      <div className="flex-1 overflow-y-auto p-6">
        {/* Search Bar */}
        <div className="space-y-4 mb-6">
          {/* 本地搜索 + 筛选按钮 */}
          <div className="flex gap-4">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="搜索论文（标题、作者、标签）..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10"
              />
            </div>
            <Button
              variant="outline"
              onClick={() => setShowFilters(!showFilters)}
              className="gap-2"
            >
              <Filter className="w-4 h-4" />
              筛选
              {(selectedTags.length > 0 || filterOption !== 'all') && (
                <Badge variant="secondary" className="ml-1">
                  {selectedTags.length + (filterOption !== 'all' ? 1 : 0)}
                </Badge>
              )}
            </Button>
          </div>

          {/* 筛选和排序选项 */}
          {showFilters && (
            <PaperFilters
              filterOption={filterOption}
              setFilterOption={setFilterOption}
              sortOption={sortOption}
              setSortOption={setSortOption}
              allTags={allTags}
              selectedTags={selectedTags}
              toggleTagFilter={toggleTagFilter}
              showFilters={showFilters}
            />
          )}
        </div>

        {/* Papers List */}
        {isLoadingPapers ? (
          <PaperListSkeleton count={pageSize} />
        ) : filteredPapers.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-16">
              <FileText className="w-16 h-16 text-muted-foreground mb-4" />
              <h3 className="text-lg font-medium mb-2">暂无论文</h3>
              <p className="text-muted-foreground text-center max-w-md mb-6">
                还没有收藏的论文。点击"抓取论文"按钮，从 arXiv 获取最新的计算机视觉论文。
              </p>
              <div className="flex gap-2">
                <Button onClick={() => setActiveTool('fetch')} disabled={!isConnected || isFetching}>
                  <Plus className="w-4 h-4 mr-2" />
                  抓取论文
                </Button>
                <Button variant="outline" onClick={loadLocalPapersData}>
                  <RefreshCw className="w-4 h-4 mr-2" />
                  刷新
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : (
          <>
            {/* 批量操作工具栏 */}
            {isBatchMode ? (
              <div className="mb-4 p-3 bg-muted rounded-lg flex items-center justify-between flex-wrap gap-3">
                <div className="flex items-center gap-3">
                  <span className="text-sm font-medium">
                    已选择 {selectedPapers.size} 篇
                  </span>
                  <Button variant="ghost" size="sm" onClick={toggleSelectAll}>
                    {paginatedPapers.every((p) => selectedPapers.has(p.id)) ? '取消全选' : '全选本页'}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={clearSelection}>
                    取消选择
                  </Button>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  {showBatchTagInput ? (
                    <div className="flex gap-2">
                      <Input
                        placeholder="输入标签，逗号分隔"
                        value={batchTagInput}
                        onChange={(e) => setBatchTagInput(e.target.value)}
                        className="w-48 h-8"
                        autoFocus
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleBatchAddTags()
                          if (e.key === 'Escape') setShowBatchTagInput(false)
                        }}
                      />
                      <Button size="sm" className="h-8" onClick={handleBatchAddTags}>添加</Button>
                      <Button size="sm" variant="ghost" className="h-8" onClick={() => setShowBatchTagInput(false)}>取消</Button>
                    </div>
                  ) : (
                    <Button variant="outline" size="sm" onClick={() => setShowBatchTagInput(true)}>
                      <Tag className="w-4 h-4 mr-1" />
                      添加标签
                    </Button>
                  )}
                  <Button variant="outline" size="sm" onClick={() => handleBatchMarkRead(true)}>
                    <CheckCircle className="w-4 h-4 mr-1" />
                    标为已读
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => handleBatchMarkRead(false)}>
                    <EyeOff className="w-4 h-4 mr-1" />
                    标为未读
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => handleBatchFavorite(true)}>
                    <Star className="w-4 h-4 mr-1" />
                    收藏
                  </Button>
                  <Button variant="destructive" size="sm" onClick={handleBatchDelete}>
                    <Trash2 className="w-4 h-4 mr-1" />
                    删除
                  </Button>
                </div>
              </div>
            ) : null}

            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <p className="text-sm text-muted-foreground">
                  共 {filteredPapers.length} 篇论文
                  {searchQuery && ` (搜索 "${searchQuery}" 的结果)`}
                </p>
                {filteredPapers.length > 0 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setIsBatchMode(!isBatchMode)}
                  >
                    {isBatchMode ? '退出批量' : '批量操作'}
                  </Button>
                )}
              </div>
              <div className="flex items-center gap-2">
                {/* 每页数量选择 */}
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value))
                    setCurrentPage(1)
                  }}
                  className="text-sm border rounded px-2 py-1 bg-background"
                >
                  <option value={10}>10条/页</option>
                  <option value={20}>20条/页</option>
                  <option value={50}>50条/页</option>
                </select>
                <Button variant="outline" size="sm" onClick={loadLocalPapersData}>
                  <RefreshCw className="w-4 h-4 mr-2" />
                  刷新
                </Button>
              </div>
            </div>

            <div className="grid gap-4">
              {paginatedPapers.map((paper) => (
                <PaperCard
                  key={paper.id}
                  paper={paper}
                  isExpanded={expandedAbstracts.has(paper.id) || expandedAbstracts.has(`summary-${paper.id}`)}
                  isSelected={selectedPapers.has(paper.id)}
                  isBatchMode={isBatchMode}
                  isSummarizing={summarizingIds.has(paper.id)}
                  onToggleExpand={() => handleExpandAbstract(paper)}
                  onToggleRead={() => toggleRead(paper.id, paper.isRead)}
                  onToggleFavorite={() => toggleFavorite(paper.id, paper.isFavorite)}
                  onSummarize={() => handleSummarize(paper)}
                  onDownloadPDF={() => handleDownloadPDF(paper.arxivId, paper.title)}
                  onPreviewPDF={() => {
                    // 后端 GET /api/papers/{arxivId}/pdf 支持懒下载：localPath 不存在
                    // 时直接打预览，后端会先 download_pdf 落盘并流式返回。原来这里
                    // 的 paper.localPath 守卫是死代码——localPath 为空根本进不来。
                    setPdfPreview({
                      isOpen: true,
                      url: `/api/papers/${paper.arxivId}/pdf`,
                      title: paper.title,
                    })
                  }}
                  onDelete={() => showDeleteConfirm(paper.id, paper.title)}
                  onSelect={() => togglePaperSelection(paper.id)}
                  onEditTags={(tags) => updatePaper(paper.id, { tags })}
                  onGenerateBibtex={() => setBibtexPaperId(paper.id)}
                />
              ))}
            </div>

            {/* 分页组件 */}
            {totalPages > 1 && (
              <div className="mt-6 flex items-center justify-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                >
                  <ChevronLeft className="w-4 h-4" />
                </Button>

                <div className="flex items-center gap-1">
                  {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                    // 显示当前页附近的页码
                    let pageNum
                    if (totalPages <= 5) {
                      pageNum = i + 1
                    } else if (currentPage <= 3) {
                      pageNum = i + 1
                    } else if (currentPage >= totalPages - 2) {
                      pageNum = totalPages - 4 + i
                    } else {
                      pageNum = currentPage - 2 + i
                    }

                    return (
                      <Button
                        key={pageNum}
                        variant={currentPage === pageNum ? 'default' : 'outline'}
                        size="sm"
                        className="w-8 h-8 p-0"
                        onClick={() => setCurrentPage(pageNum)}
                      >
                        {pageNum}
                      </Button>
                    )
                  })}
                  {totalPages > 5 && currentPage < totalPages - 2 && (
                    <>
                      <span className="px-2">...</span>
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-8 h-8 p-0"
                        onClick={() => setCurrentPage(totalPages)}
                      >
                        {totalPages}
                      </Button>
                    </>
                  )}
                </div>

                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  disabled={currentPage === totalPages}
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>

                <span className="text-sm text-muted-foreground ml-4">
                  第 {currentPage} / {totalPages} 页
                </span>
              </div>
            )}
          </>
        )}
      </div>
      ) : activeTool === 'fetch' ? (
        <FetchPapersTab
          lastResult={lastFetchResult}
          isFetching={isFetching}
          onFetch={(params) => handleFetchPapers(params)}
        />
      ) : (
        <div className="flex-1 overflow-hidden">
          <CitationHub embedded />
        </div>
      )}

      {/* 删除确认对话框 */}
      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        title="删除论文"
        message={`确定要删除论文 "${confirmDialog.title}" 吗？此操作不可恢复。`}
        confirmText="删除"
        cancelText="取消"
        variant="danger"
        onConfirm={handleDeletePaper}
        onCancel={() => setConfirmDialog((prev) => ({ ...prev, isOpen: false }))}
      />

      {/* Toast 通知 */}
      <ToastContainer />

      {/* PDF 预览对话框 */}
      <PDFPreviewDialog
        isOpen={pdfPreview.isOpen}
        url={pdfPreview.url}
        title={pdfPreview.title}
        onClose={() => setPdfPreview({ ...pdfPreview, isOpen: false })}
      />

      {/* 生成 BibTeX 弹窗（嵌入引用工具，保存后回填论文） */}
      {bibtexPaper && (
        <div
          className="fixed inset-0 z-[90] bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => setBibtexPaperId(null)}
          aria-modal="true"
          role="dialog"
          aria-label="生成 BibTeX 引用"
        >
          <div
            className="w-full max-w-4xl h-[80vh] glass rounded-2xl shadow-2xl border border-border/50 overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-3 border-b shrink-0">
              <div>
                <h3 className="font-display font-semibold flex items-center gap-2">
                  生成 BibTeX 引用
                </h3>
                <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                  {bibtexPaper.title}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setBibtexPaperId(null)}
                aria-label="关闭"
              >
                <X className="w-5 h-5" />
              </Button>
            </div>
            <div className="flex-1 overflow-hidden">
              <CitationHub
                embedded
                initialPaper={{
                  title: bibtexPaper.title,
                  authors: bibtexPaper.authors,
                  year: bibtexPaper.publishedDate
                    ? parseInt(bibtexPaper.publishedDate.slice(0, 4), 10)
                    : null,
                  arxivId: bibtexPaper.arxivId,
                  // doi 待数据库扩展后传入
                }}
                onInsert={(_, bibtex) => handleSaveBibtex(bibtexPaper.id, bibtex)}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
