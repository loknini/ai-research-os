/**
 * Paper Hub 的筛选面板（排序 / 阅读状态 / 标签）。
 * 源自原 monolith index.tsx 514–605 行，抽离为纯展示组件。
 * 状态与切换逻辑由容器通过 props 注入，组件本身不持有 state。
 */

import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ArrowUpDown, BookOpen, Tag, X } from 'lucide-react'
import type { SortOption, FilterOption } from '../types'
import { SORT_OPTIONS, FILTER_OPTIONS } from '../config'

export interface PaperFiltersProps {
  filterOption: FilterOption
  setFilterOption: (option: FilterOption) => void
  sortOption: SortOption
  setSortOption: (option: SortOption) => void
  allTags: string[]
  selectedTags: string[]
  toggleTagFilter: (tag: string) => void
  showFilters: boolean
}

/**
 * 排序 / 状态 / 标签 筛选 UI 面板。
 *「清除筛选」按钮在 filterOption 与 selectedTags 都由本组件 props 控制的前提下，
 * 通过 setFilterOption('all') + 逐个 toggleTagFilter 还原标签选择，保持与原 monolith 行为一致。
 */
export default function PaperFilters({
  filterOption,
  setFilterOption,
  sortOption,
  setSortOption,
  allTags,
  selectedTags,
  toggleTagFilter,
  showFilters
}: PaperFiltersProps) {
  if (!showFilters) return null

  return (
    <Card className="bg-muted/50">
      <CardContent className="pt-4 space-y-4">
        {/* 排序选项 */}
        <div>
          <label className="text-sm font-medium mb-2 flex items-center gap-2">
            <ArrowUpDown className="w-4 h-4" />
            排序方式
          </label>
          <div className="flex gap-2 flex-wrap">
            {SORT_OPTIONS.map((option) => (
              <Button
                key={option.value}
                variant={sortOption === option.value ? 'default' : 'outline'}
                size="sm"
                onClick={() => setSortOption(option.value)}
              >
                {option.label}
              </Button>
            ))}
          </div>
        </div>

        {/* 阅读状态筛选 */}
        <div>
          <label className="text-sm font-medium mb-2 flex items-center gap-2">
            <BookOpen className="w-4 h-4" />
            阅读状态
          </label>
          <div className="flex gap-2 flex-wrap">
            {FILTER_OPTIONS.map((option) => (
              <Button
                key={option.value}
                variant={filterOption === option.value ? 'default' : 'outline'}
                size="sm"
                onClick={() => setFilterOption(option.value)}
              >
                {option.label}
              </Button>
            ))}
          </div>
        </div>

        {/* 标签筛选 */}
        {allTags.length > 0 && (
          <div>
            <label className="text-sm font-medium mb-2 flex items-center gap-2">
              <Tag className="w-4 h-4" />
              标签筛选
            </label>
            <div className="flex gap-2 flex-wrap">
              {allTags.map((tag) => (
                <Badge
                  key={tag}
                  variant={selectedTags.includes(tag) ? 'default' : 'outline'}
                  className="cursor-pointer"
                  onClick={() => toggleTagFilter(tag)}
                >
                  {tag}
                  {selectedTags.includes(tag) && <X className="w-3 h-3 ml-1" />}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* 清除筛选 */}
        {(selectedTags.length > 0 || filterOption !== 'all') && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setFilterOption('all')
              selectedTags.forEach((tag) => toggleTagFilter(tag))
            }}
          >
            清除筛选
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
