/**
 * Paper Hub 的「抓取论文」Tab 内容（替代原 FetchPapersDialog 弹窗）。
 *
 * 设计：
 * - 顶部：搜索表单（关键词 + 抓取数量 + 提交）
 * - 下方：本次抓取的实时预览（按"新增/已存在"标注），不打断用户阅读
 * - 抓取成功后自动滚到结果区域
 * - 切到「论文管理」Tab 即可看到新论文已入库
 */
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Plus, RefreshCw, FileText, ExternalLink, Search as SearchIcon } from 'lucide-react'
import type { Paper } from '@/types'

export interface FetchBatchResult {
  papers: Paper[]
  total: number
  /** 本次新增数量（=后端 inserted） */
  inserted: number
  /** 抓取时刻（用于在 Tab 内分组显示） */
  fetchedAt: number
  /** 抓取时用的关键词（回显） */
  keywords: string
  maxResults: number
}

interface FetchPapersTabProps {
  /** 本次（最后一次）抓取结果，未抓取过为 null */
  lastResult: FetchBatchResult | null
  isFetching: boolean
  onFetch: (params: { keywords: string; maxResults: number }) => void
}

export default function FetchPapersTab({ lastResult, isFetching, onFetch }: FetchPapersTabProps) {
  const [keywords, setKeywords] = useState('')
  const [maxResults, setMaxResults] = useState(10)
  const resultsRef = useRef<HTMLDivElement | null>(null)

  // 抓取成功后把结果区滚到视口里（实时感）
  useEffect(() => {
    if (lastResult && resultsRef.current) {
      resultsRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [lastResult])

  const handleSubmit = () => {
    if (isFetching) return
    onFetch({ keywords, maxResults })
  }

  const trimmed = keywords.trim()
  const duplicates = lastResult ? lastResult.papers.length - lastResult.inserted : 0

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-5xl mx-auto space-y-6">
        {/* 搜索表单 */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SearchIcon className="w-5 h-5" />
              抓取论文
            </CardTitle>
            <CardDescription>
              从 arXiv 检索并入库。逗号分隔多个关键词；留空抓取最新 CV 论文。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-2 block">搜索关键词</label>
              <Input
                placeholder="例如: object detection, transformer, diffusion..."
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
              />
              <p className="text-xs text-muted-foreground mt-1">
                留空则抓取所有 CV 论文（默认 cat:cs.CV）
              </p>
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">抓取数量</label>
              <Input
                type="number"
                min={1}
                max={50}
                value={maxResults}
                onChange={(e) => setMaxResults(Math.min(50, Math.max(1, parseInt(e.target.value) || 10)))}
              />
              <p className="text-xs text-muted-foreground mt-1">最多 50 篇</p>
            </div>
            <div className="flex items-center gap-2">
              <Button onClick={handleSubmit} disabled={isFetching}>
                {isFetching ? (
                  <>
                    <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                    抓取中...
                  </>
                ) : (
                  <>
                    <Plus className="w-4 h-4 mr-2" />
                    {trimmed
                      ? `搜索 "${trimmed.substring(0, 20)}${trimmed.length > 20 ? '...' : ''}"`
                      : '抓取最新 CV 论文'}
                  </>
                )}
              </Button>
              {lastResult && (
                <span className="text-xs text-muted-foreground">
                  上次抓取于 {new Date(lastResult.fetchedAt).toLocaleTimeString()}
                </span>
              )}
            </div>
          </CardContent>
        </Card>

        {/* 本次抓取结果预览 */}
        <div ref={resultsRef}>
          {!lastResult ? (
            <Card className="bg-muted/30 border-dashed">
              <CardContent className="py-12 text-center text-muted-foreground">
                <FileText className="w-10 h-10 mx-auto mb-3 opacity-40" />
                <p className="text-sm">尚未抓取。提交上方表单开始第一次检索。</p>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  本次抓取结果
                  <Badge variant="secondary">{lastResult.papers.length}</Badge>
                  {lastResult.inserted > 0 && (
                    <Badge className="bg-green-100 text-green-700 hover:bg-green-100">
                      新增 {lastResult.inserted}
                    </Badge>
                  )}
                  {duplicates > 0 && (
                    <Badge variant="outline">已存在 {duplicates}</Badge>
                  )}
                </CardTitle>
                <CardDescription>
                  关键词：{lastResult.keywords || '（默认 cat:cs.CV）'} · 抓取 {lastResult.maxResults} 篇
                </CardDescription>
              </CardHeader>
              <CardContent>
                {lastResult.papers.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-6 text-center">
                    本次未匹配到论文。可以换个关键词再试。
                  </p>
                ) : (
                  <div className="divide-y">
                    {lastResult.papers.map((p, idx) => {
                      // 本次是否新增：用 fetchedAt + 在 papers 数组中的索引（后端顺序与返回顺序一致）
                      // 用论文的 id 简单做"是否本次新增"：需要外部传入 insertedIds 更准，
                      // 这里用 lastResult.inserted 数 + 顺序做近似。
                      const isNew = idx < lastResult.inserted
                      return (
                        <div key={p.id || p.arxivId} className="py-3 flex items-start gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              {isNew ? (
                                <Badge className="bg-blue-100 text-blue-700 hover:bg-blue-100 text-xs">
                                  新增
                                </Badge>
                              ) : (
                                <Badge variant="outline" className="text-xs">
                                  已存在
                                </Badge>
                              )}
                              <h4 className="font-medium text-sm line-clamp-2">{p.title}</h4>
                            </div>
                            <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                              <span className="line-clamp-1">
                                {(p.authors || []).slice(0, 3).join(', ')}
                                {(p.authors || []).length > 3 && ' 等'}
                              </span>
                              {p.arxivId && <span>· {p.arxivId}</span>}
                              {p.publishedDate && <span>· {p.publishedDate}</span>}
                              {p.categories?.slice(0, 2).map((c) => (
                                <Badge key={c} variant="outline" className="text-[10px]">
                                  {c}
                                </Badge>
                              ))}
                            </div>
                          </div>
                          <a
                            href={`https://arxiv.org/abs/${p.arxivId}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-muted-foreground hover:text-primary flex-shrink-0 mt-1"
                            title="在 arXiv 查看"
                          >
                            <ExternalLink className="w-4 h-4" />
                          </a>
                        </div>
                      )
                    })}
                  </div>
                )}
                <p className="mt-4 text-xs text-muted-foreground">
                  切到「论文管理」Tab 可对新论文执行总结、引用、下载 PDF 等操作。
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
