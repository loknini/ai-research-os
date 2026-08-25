/**
 * Paper Hub 常量元数据。
 * 源自原 monolith index.tsx 524–538（排序选项）与 549–564（筛选选项），
 * 统一收敛为 SORT_OPTIONS / FILTER_OPTIONS，供 PaperFilters 与容器共享。
 */

import type { SortOption, FilterOption } from './types'

/** 排序选项元数据 */
export const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: 'date-desc', label: '最新发布' },
  { value: 'date-asc', label: '最早发布' },
  { value: 'title-asc', label: '标题 A-Z' },
  { value: 'title-desc', label: '标题 Z-A' },
]

/** 阅读状态筛选选项元数据 */
export const FILTER_OPTIONS: { value: FilterOption; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'unread', label: '未读' },
  { value: 'read', label: '已读' },
  { value: 'favorite', label: '收藏' },
]
