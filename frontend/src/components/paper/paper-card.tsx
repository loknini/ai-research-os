import { memo, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Star,
  CheckCircle,
  FileText,
  RefreshCw,
  EyeOff,
  Trash2,
  ChevronDown,
  ChevronUp,
  Tag,
  CheckSquare,
  Square,
  Eye,
  Quote
} from 'lucide-react'
import { cn, formatDate } from '@/utils'
import type { Paper } from '@/types'

interface PaperCardProps {
  paper: Paper
  isExpanded: boolean
  isSelected?: boolean
  isBatchMode?: boolean
  isSummarizing?: boolean
  onToggleExpand: () => void
  onToggleRead: () => void
  onToggleFavorite: () => void
  onSummarize: () => void
  onPreviewPDF?: () => void
  onDelete: () => void
  onSelect?: () => void
  onEditTags?: (tags: string[]) => void
  onGenerateBibtex?: () => void
}

export const PaperCard = memo(function PaperCard({
  paper,
  isExpanded,
  isSelected,
  isBatchMode,
  isSummarizing,
  onToggleExpand,
  onToggleRead,
  onToggleFavorite,
  onSummarize,
  onPreviewPDF,
  onDelete,
  onSelect,
  onEditTags,
  onGenerateBibtex
}: PaperCardProps) {
  const [isEditingTags, setIsEditingTags] = useState(false)
  const [tagInput, setTagInput] = useState('')

  const handleStartEditTags = useCallback(() => {
    setIsEditingTags(true)
    setTagInput((paper.tags || []).join(', '))
  }, [paper.tags])

  const handleSaveTags = useCallback(() => {
    const newTags = tagInput
      .split(/[,，]/)
      .map(t => t.trim())
      .filter(t => t.length > 0)
    onEditTags?.(newTags)
    setIsEditingTags(false)
  }, [tagInput, onEditTags])

  const truncatedAbstract = paper.abstract.slice(0, 200)
  const shouldTruncate = paper.abstract.length > 200
  const displayAbstract = isExpanded ? paper.abstract : truncatedAbstract + (shouldTruncate ? '...' : '')

  // AI 总结是 LLM 生成的 Markdown（含 ## / - / emoji 等），
  // 用 react-markdown 渲染；之前按 plain text 渲染时，markdown 标记原样
  // 暴露，用户看到的是 "## 研究背景..." 这种 raw 文本。
  // Markdown 不能截断字符串再渲染（会破坏语法），改用 max-height + 滚动条：
  // 默认露出预览高度，溢出滚动；点击展开按钮解除高度限制（不是显示/隐藏，
  // 因为完整总结是有用信息，不应该藏起来）。
  const summary = paper.summary || ''
  const hasSummary = summary.length > 0
  const SUMMARY_COLLAPSED_HEIGHT = 280
  const [isSummaryExpanded, setIsSummaryExpanded] = useState(false)
  // 文本过长才显示「展开」按钮；纯 markdown 字符比 plain text 复杂，这里阈值放宽
  const showSummaryCollapse = hasSummary && summary.length > 600

  return (
    <Card className={`hover:shadow-md transition-shadow ${isSelected ? 'ring-2 ring-primary' : ''}`}>
      <CardHeader className="pb-3">
        <div className="flex items-start gap-3">
          {/* 批量选择框 */}
          {isBatchMode && (
            <button onClick={onSelect} className="mt-1 flex-shrink-0">
              {isSelected ? (
                <CheckSquare className="w-5 h-5 text-primary" />
              ) : (
                <Square className="w-5 h-5 text-muted-foreground" />
              )}
            </button>
          )}
          <div className="flex-1 min-w-0">
            <CardTitle className="text-lg mb-1 line-clamp-2">{paper.title}</CardTitle>
            <CardDescription className="line-clamp-1">
              {paper.authors.slice(0, 5).join(', ')}
              {paper.authors.length > 5 && ` +${paper.authors.length - 5} more`}
            </CardDescription>
          </div>
          <div className="flex gap-2 flex-shrink-0">
            <Button variant="ghost" size="icon" onClick={onToggleFavorite}>
              <Star
                className={`w-5 h-5 ${paper.isFavorite ? 'text-yellow-500 fill-yellow-500' : 'text-muted-foreground'}`}
              />
            </Button>
            <Button variant="ghost" size="icon" onClick={onToggleRead}>
              {paper.isRead ? (
                <CheckCircle className="w-5 h-5 text-green-500" />
              ) : (
                <EyeOff className="w-5 h-5 text-muted-foreground" />
              )}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {/* AI 总结区域：用 react-markdown 渲染，避免 raw 文本暴露 markdown 符号 */}
        {hasSummary && (
          <div className="mb-4 p-3 bg-blue-50/50 border border-blue-100 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <FileText className="w-4 h-4 text-blue-500" />
              <span className="text-sm font-medium text-blue-700">AI 总结</span>
            </div>
            <div
              className={cn(
                'text-sm text-blue-900 paper-md',
                // 收起态：限高度 + 溢出滚动；展开态：完全展开
                showSummaryCollapse && !isSummaryExpanded
                  ? 'overflow-auto'
                  : ''
              )}
              style={
                showSummaryCollapse && !isSummaryExpanded
                  ? { maxHeight: SUMMARY_COLLAPSED_HEIGHT }
                  : undefined
              }
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h1: (props) => <h1 className="text-base font-semibold mt-3 mb-1.5" {...props} />,
                  h2: (props) => <h2 className="text-sm font-semibold mt-3 mb-1.5 flex items-center gap-1.5" {...props} />,
                  h3: (props) => <h3 className="text-sm font-semibold mt-2 mb-1" {...props} />,
                  p: (props) => <p className="leading-relaxed my-1.5" {...props} />,
                  ul: (props) => <ul className="list-disc pl-5 space-y-0.5 my-1.5 marker:text-blue-400" {...props} />,
                  ol: (props) => <ol className="list-decimal pl-5 space-y-0.5 my-1.5" {...props} />,
                  li: (props) => <li className="leading-relaxed" {...props} />,
                  strong: (props) => <strong className="font-semibold" {...props} />,
                  em: (props) => <em className="italic" {...props} />,
                  code: (props) => <code className="px-1 py-0.5 bg-blue-100/60 rounded text-xs font-mono" {...props} />,
                  a: (props) => <a className="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer" {...props} />,
                }}
              >
                {summary}
              </ReactMarkdown>
            </div>
            {showSummaryCollapse && (
              <button
                onClick={() => setIsSummaryExpanded((v) => !v)}
                className="mt-2 text-xs text-blue-600 hover:underline"
              >
                {isSummaryExpanded ? '收起' : '展开完整总结'}
              </button>
            )}
          </div>
        )}

        {/* 原始摘要区域 */}
        <div className="text-sm text-muted-foreground mb-4">
          <p className="whitespace-pre-wrap">{displayAbstract}</p>
          {shouldTruncate && (
            <button
              onClick={onToggleExpand}
              className="mt-2 text-xs text-primary hover:underline flex items-center gap-1"
            >
              {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              {isExpanded ? '收起摘要' : '展开摘要'}
            </button>
          )}
        </div>

        {/* 标签区域 */}
        <div className="mb-3">
          {isEditingTags ? (
            <div className="flex gap-2 items-center">
              <Tag className="w-4 h-4 text-muted-foreground" />
              <Input
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                placeholder="输入标签，用逗号分隔"
                className="flex-1 h-8 text-sm"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSaveTags()
                  if (e.key === 'Escape') setIsEditingTags(false)
                }}
              />
              <Button size="sm" className="h-8" onClick={handleSaveTags}>保存</Button>
              <Button size="sm" variant="ghost" className="h-8" onClick={() => setIsEditingTags(false)}>取消</Button>
            </div>
          ) : (
            <div
              className="flex gap-2 flex-wrap items-center cursor-pointer group"
              onClick={handleStartEditTags}
            >
              <Tag className="w-4 h-4 text-muted-foreground" />
              {paper.tags && paper.tags.length > 0 ? (
                paper.tags.map(tag => (
                  <Badge key={tag} variant="secondary" className="text-xs">{tag}</Badge>
                ))
              ) : (
                <span className="text-xs text-muted-foreground group-hover:text-primary">+ 添加标签</span>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex gap-2 flex-wrap">
            <Badge variant="secondary">{paper.arxivId}</Badge>
            <Badge variant="outline">{formatDate(paper.publishedDate)}</Badge>
            {paper.categories?.slice(0, 2).map(cat => (
              <Badge key={cat} variant="outline" className="text-xs">{cat}</Badge>
            ))}
          </div>

          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onSummarize}
              disabled={isSummarizing}
            >
              {isSummarizing ? (
                <RefreshCw className="w-4 h-4 mr-1 animate-spin" />
              ) : (
                <FileText className="w-4 h-4 mr-1" />
              )}
              {paper.summary ? '重新总结' : '总结'}
            </Button>
            {onGenerateBibtex && (
              <Button
                variant="outline"
                size="sm"
                onClick={onGenerateBibtex}
                className={paper.bibtex ? 'text-green-600 border-green-300 hover:bg-green-50' : ''}
                title={paper.bibtex ? '已保存 BibTeX，点击更新' : '生成 BibTeX 引用并保存'}
              >
                <Quote className={`w-4 h-4 mr-1 ${paper.bibtex ? 'text-green-600' : ''}`} />
                {paper.bibtex ? 'BibTeX ✓' : '引用'}
              </Button>
            )}
            {/* 预览按钮：后端 GET /api/papers/{arxivId}/pdf 支持懒下载，
                localPath 为空也能直接预览（之前要求 localPath 存在才能预览是死代码） */}
            {onPreviewPDF && (
              <Button
                variant="outline"
                size="sm"
                onClick={onPreviewPDF}
                title="在浏览器内打开 PDF（懒下载：若未下载后端会先下载）"
              >
                <Eye className="w-4 h-4 mr-1" />
                查看
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={onDelete}
              className="text-red-500 hover:text-red-600 hover:bg-red-50"
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
})
