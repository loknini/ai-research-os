/**
 * Paper Hub 本地类型。
 * 原 monolith（index.tsx 33–34 行）中的 SortOption / FilterOption，
 * 搬移至本文件后由本 Hub 内各模块共享，保持零破坏性。
 */

/** 排序选项 */
export type SortOption = 'date-desc' | 'date-asc' | 'title-asc' | 'title-desc'

/** 筛选选项（阅读状态） */
export type FilterOption = 'all' | 'unread' | 'read' | 'favorite'
