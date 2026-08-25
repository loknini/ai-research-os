/**
 * Paper Hub 的派生数据与批量操作 hook。
 *
 * 将原 monolith 中的「派生状态 + 批量选择处理函数」统一收敛到本 hook：
 *  - allTags / filteredPapers / totalPages / paginatedPapers（307–362）
 *  - 分页重置 effect（365–367）
 *  - toggleTagFilter（298–304）
 *  - 批量选择 state + handlers（370–468）：
 *    togglePaperSelection / toggleSelectAll / clearSelection /
 *    handleBatchDelete / handleBatchMarkRead / handleBatchAddTags / handleBatchFavorite
 *
 * 容器把所有相关 state + setter 以及来自 store 的 updatePaper / deletePaper、以及
 * showToast 作为入参传入；本 hook 不持有任何业务 state，纯派生 + 透传动作。
 */

import { useEffect, useMemo, type Dispatch, type SetStateAction } from 'react'
import type { Paper } from '@/types'
import type { SortOption, FilterOption } from '../types'
import { batchDeletePapers } from '../services/papersApi'

/** showToast 的类型（与 @/components/ui/toast 的 useToast 签名一致） */
type ToastType = 'success' | 'error' | 'info'

export interface UsePaperDataParams {
  /** 来自 store 的全量论文列表 */
  papers: Paper[]
  /** 搜索关键词 */
  searchQuery: string
  /** 阅读状态筛选 */
  filterOption: FilterOption
  /** 排序方式 */
  sortOption: SortOption
  /** 已选标签 */
  selectedTags: string[]
  /** 设置已选标签（toggleTagFilter 使用） */
  setSelectedTags: Dispatch<SetStateAction<string[]>>
  /** 当前页码 */
  currentPage: number
  /** 设置当前页码（分页重置 effect 使用） */
  setCurrentPage: (page: number) => void
  /** 每页数量 */
  pageSize: number
  /** 已勾选的论文 id 集合 */
  selectedPapers: Set<string>
  /** 设置已勾选集合 */
  setSelectedPapers: Dispatch<SetStateAction<Set<string>>>
  /** 设置是否处于批量模式（clearSelection 使用） */
  setIsBatchMode: (value: boolean) => void
  /** 批量打标签输入框内容 */
  batchTagInput: string
  /** 设置批量打标签输入框内容 */
  setBatchTagInput: (value: string) => void
  /** 设置是否展示批量打标签输入框 */
  setShowBatchTagInput: (value: boolean) => void
  /** store action：更新单篇论文 */
  updatePaper: (id: string, updates: Partial<Paper>) => void
  /** store action：删除单篇论文 */
  deletePaper: (id: string) => void
  /** 全局 toast */
  showToast: (message: string, type: ToastType) => void
}

export interface UsePaperDataResult {
  allTags: string[]
  filteredPapers: Paper[]
  totalPages: number
  paginatedPapers: Paper[]
  toggleTagFilter: (tag: string) => void
  togglePaperSelection: (paperId: string) => void
  toggleSelectAll: () => void
  clearSelection: () => void
  handleBatchDelete: () => Promise<void>
  handleBatchMarkRead: (isRead: boolean) => void
  handleBatchAddTags: () => void
  handleBatchFavorite: (isFavorite: boolean) => void
}

export function usePaperData({
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
}: UsePaperDataParams): UsePaperDataResult {
  // 获取所有可用标签（307–311）
  const allTags = useMemo(() => {
    const tagSet = new Set<string>()
    papers.forEach((p) => p.tags?.forEach((t) => tagSet.add(t)))
    return Array.from(tagSet).sort()
  }, [papers])

  // 筛选和排序论文（314–355）
  const filteredPapers = useMemo(() => {
    const result = papers.filter((paper) => {
      // 文本搜索
      const matchesSearch =
        searchQuery === '' ||
        paper.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        paper.abstract.toLowerCase().includes(searchQuery.toLowerCase()) ||
        paper.authors.some((author) => author.toLowerCase().includes(searchQuery.toLowerCase())) ||
        paper.tags?.some((tag) => tag.toLowerCase().includes(searchQuery.toLowerCase()))

      // 阅读状态筛选
      let matchesFilter = true
      if (filterOption === 'unread') matchesFilter = !paper.isRead
      if (filterOption === 'read') matchesFilter = paper.isRead
      if (filterOption === 'favorite') matchesFilter = paper.isFavorite

      // 标签筛选
      const matchesTags =
        selectedTags.length === 0 || selectedTags.some((tag) => paper.tags?.includes(tag))

      return matchesSearch && matchesFilter && matchesTags
    })

    // 排序
    result.sort((a, b) => {
      switch (sortOption) {
        case 'date-desc':
          return new Date(b.publishedDate).getTime() - new Date(a.publishedDate).getTime()
        case 'date-asc':
          return new Date(a.publishedDate).getTime() - new Date(b.publishedDate).getTime()
        case 'title-asc':
          return a.title.localeCompare(b.title)
        case 'title-desc':
          return b.title.localeCompare(a.title)
        default:
          return 0
      }
    })

    return result
  }, [papers, searchQuery, filterOption, sortOption, selectedTags])

  // 分页逻辑（357–362）
  const totalPages = Math.ceil(filteredPapers.length / pageSize)
  const paginatedPapers = useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return filteredPapers.slice(start, start + pageSize)
  }, [filteredPapers, currentPage, pageSize])

  // 重置分页当筛选条件变化（365–367）
  useEffect(() => {
    setCurrentPage(1)
  }, [searchQuery, filterOption, selectedTags, sortOption])

  // 标签筛选切换（298–304）
  const toggleTagFilter = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    )
  }

  // 批量操作处理函数（370–468）

  const togglePaperSelection = (paperId: string) => {
    setSelectedPapers((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(paperId)) {
        newSet.delete(paperId)
      } else {
        newSet.add(paperId)
      }
      return newSet
    })
  }

  const toggleSelectAll = () => {
    const currentIds = new Set(paginatedPapers.map((p) => p.id))
    const allSelected = paginatedPapers.every((p) => selectedPapers.has(p.id))

    if (allSelected) {
      // 取消全选当前页
      setSelectedPapers((prev) => {
        const newSet = new Set(prev)
        currentIds.forEach((id) => newSet.delete(id))
        return newSet
      })
    } else {
      // 全选当前页
      setSelectedPapers((prev) => {
        const newSet = new Set(prev)
        currentIds.forEach((id) => newSet.add(id))
        return newSet
      })
    }
  }

  const clearSelection = () => {
    setSelectedPapers(new Set())
    setIsBatchMode(false)
  }

  const handleBatchDelete = async () => {
    if (selectedPapers.size === 0) return

    const confirmed = window.confirm(`确定要删除选中的 ${selectedPapers.size} 篇论文吗？`)
    if (!confirmed) return

    const ids = Array.from(selectedPapers)
    const successCount = await batchDeletePapers(ids)
    // 本地状态移除（保留原 monolith 逐篇 deletePaper 的本地清理语义）
    ids.forEach((id) => deletePaper(id))

    showToast(`已删除 ${successCount} 篇论文`, 'success')
    clearSelection()
  }

  const handleBatchMarkRead = (isRead: boolean) => {
    selectedPapers.forEach((paperId) => {
      updatePaper(paperId, { isRead })
    })
    showToast(`已标记 ${selectedPapers.size} 篇论文为${isRead ? '已读' : '未读'}`, 'success')
    clearSelection()
  }

  const handleBatchAddTags = () => {
    const tags = batchTagInput
      .split(/[,，]/)
      .map((t) => t.trim())
      .filter((t) => t.length > 0)

    if (tags.length === 0) return

    selectedPapers.forEach((paperId) => {
      const paper = papers.find((p) => p.id === paperId)
      if (paper) {
        const existingTags = paper.tags || []
        const newTags = [...new Set([...existingTags, ...tags])]
        updatePaper(paperId, { tags: newTags })
      }
    })

    showToast(`已为 ${selectedPapers.size} 篇论文添加标签`, 'success')
    setBatchTagInput('')
    setShowBatchTagInput(false)
    clearSelection()
  }

  const handleBatchFavorite = (isFavorite: boolean) => {
    selectedPapers.forEach((paperId) => {
      updatePaper(paperId, { isFavorite })
    })
    showToast(`已${isFavorite ? '收藏' : '取消收藏'} ${selectedPapers.size} 篇论文`, 'success')
    clearSelection()
  }

  return {
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
  }
}
