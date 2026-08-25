import { memo, useState, useCallback } from 'react'
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
  Download,
  CheckSquare,
  Square,
  Eye,
  Quote
} from 'lucide-react'
import { formatDate } from '@/utils'
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
  onDownloadPDF: () => void
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
  onDownloadPDF,
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
        {/* AI 总结区域 */}
        {paper.summary && (
          <div className="mb-4 p-3 bg-blue-50/50 border border-blue-100 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <FileText className="w-4 h-4 text-blue-500" />
              <span className="text-sm font-medium text-blue-700">AI 总结</span>
            </div>
            <div className="text-sm text-blue-900 whitespace-pre-wrap">
              {displayAbstract}
              {shouldTruncate && (
                <button onClick={onToggleExpand} className="ml-2 text-xs text-blue-600 hover:underline">
                  {isExpanded ? '收起' : '展开'}
                </button>
              )}
            </div>
          </div>
        )}

        {/* 原始摘要区域 */}
        <div className="text-sm text-muted-foreground mb-4">
          <p className="whitespace-pre-wrap">{displayAbstract}</p>
          {shouldTruncate && !paper.summary && (
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
            {paper.localPath ? (
              <Button variant="outline" size="sm" asChild>
                <a href={`file://${paper.localPath}`} target="_blank" rel="noopener noreferrer">
                  <FileText className="w-4 h-4 mr-1" />
                  查看
                </a>
              </Button>
            ) : (
              <>
                {onPreviewPDF && paper.localPath && (
                  <Button variant="outline" size="sm" onClick={onPreviewPDF}>
                    <Eye className="w-4 h-4 mr-1" />
                    预览
                  </Button>
                )}
                <Button variant="outline" size="sm" onClick={onDownloadPDF}>
                  <Download className="w-4 h-4 mr-1" />
                  下载
                </Button>
              </>
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
