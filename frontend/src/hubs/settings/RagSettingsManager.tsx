import { useState, useCallback, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { toast } from '@/components/ui/toast'
import { cn } from '@/utils'
import {
  FolderSearch,
  RefreshCw,
  Trash2,
  Loader2,
  Database,
  FileText,
  AlertCircle,
  CheckCircle2,
  KeyRound,
} from 'lucide-react'

// ===================== 类型 =====================
interface RagSource {
  id: string
  spaceId: string
  name: string
  targetPaths: string[]
  recursive: boolean
  fileTypes: string[]
  status: 'pending' | 'indexing' | 'ready' | 'partial' | 'failed' | 'cancelled'
  docCount: number
  chunkCount: number
  embeddingModel: string | null
  embedMode: 'vector' | 'keyword'
  error: string | null
  createdAt: number
  updatedAt: number
}

interface RagDoc {
  id: string
  sourceId: string
  fileName: string
  filePath: string
  fileType: string
  fileSize: number
  pageCount: number
  charCount: number
  chunkCount: number
}

interface RagStats {
  sourceCount: number
  docCount: number
  chunkCount: number
  vectorCount: number
}

interface Capabilities {
  embeddingsConfigured: boolean
  embeddingModel: string
  supportedTypes: string[]
  pdfAvailable: boolean
}

const TYPE_LABELS: Record<string, string> = { pdf: 'PDF', txt: 'TXT', md: 'Markdown' }

const STATUS_META: Record<string, { label: string; cls: string }> = {
  pending: { label: '排队中', cls: 'bg-gray-500/10 text-gray-600' },
  indexing: { label: '索引中', cls: 'bg-blue-500/10 text-blue-600' },
  ready: { label: '就绪', cls: 'bg-green-500/10 text-green-600' },
  partial: { label: '部分完成', cls: 'bg-yellow-500/10 text-yellow-600' },
  failed: { label: '失败', cls: 'bg-red-500/10 text-red-600' },
  cancelled: { label: '已取消', cls: 'bg-gray-500/10 text-gray-600' },
}

/**
 * RAG 文档检索的设置面板：负责「索引源」的录入、索引、重建、删除与文档浏览。
 * 问答检索本身不在本面板（已接入 Chat Hub 的「文档检索」开关）。
 */
export default function RagSettingsManager() {
  // ---- 能力 & 列表 ----
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [sources, setSources] = useState<RagSource[]>([])
  const [stats, setStats] = useState<RagStats | null>(null)
  const [docsBySource, setDocsBySource] = useState<Record<string, RagDoc[]>>({})

  // ---- 索引表单 ----
  const [pathsText, setPathsText] = useState('')
  const [recursive, setRecursive] = useState(true)
  const [types, setTypes] = useState<Record<string, boolean>>({ pdf: true, txt: true, md: true })
  const [embedModel, setEmbedModel] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [indexing, setIndexing] = useState(false)

  const [expandedSource, setExpandedSource] = useState<string | null>(null)
  const isPolling = sources.some((s) => s.status === 'indexing')

  // ---------- 拉取能力 / 源列表 ----------
  const loadCapabilities = useCallback(async () => {
    try {
      const r = await fetch('/api/rag/capabilities')
      const j = await r.json()
      if (j.success) setCaps(j)
    } catch {
      /* ignore */
    }
  }, [])

  const loadSources = useCallback(async () => {
    try {
      const r = await fetch('/api/rag/sources')
      const j = await r.json()
      if (j.success) {
        setSources(j.sources || [])
        setStats(j.stats || null)
      }
    } catch {
      /* ignore */
    }
  }, [])

  const loadDocs = useCallback(async (sourceId: string) => {
    try {
      const r = await fetch(`/api/rag/documents?sourceId=${encodeURIComponent(sourceId)}`)
      const j = await r.json()
      if (j.success) {
        setDocsBySource((prev) => ({ ...prev, [sourceId]: j.documents || [] }))
      }
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    loadCapabilities()
    loadSources()
  }, [loadCapabilities, loadSources])

  // 索引进行中时轮询
  useEffect(() => {
    if (!isPolling) return
    const t = setInterval(() => {
      loadSources()
    }, 2000)
    return () => clearInterval(t)
  }, [isPolling, loadSources])

  // 展开源时加载文档
  useEffect(() => {
    if (expandedSource) loadDocs(expandedSource)
  }, [expandedSource, loadDocs])

  // ---------- 提交索引 ----------
  const submitIndex = useCallback(async () => {
    const paths = pathsText
      .split('\n')
      .map((p) => p.trim())
      .filter(Boolean)
    if (paths.length === 0) {
      toast({ title: '请至少填写一个目标路径（文件或目录）', variant: 'error' })
      return
    }
    const selectedTypes = Object.entries(types)
      .filter(([, v]) => v)
      .map(([k]) => k)
    const fileTypes = selectedTypes.length > 0 ? selectedTypes : ['pdf', 'txt', 'md']

    setIndexing(true)
    try {
      const r = await fetch('/api/rag/index', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          paths,
          recursive,
          fileTypes,
          embedModel: embedModel.trim() || undefined,
        }),
      })
      const j = await r.json()
      if (j.success) {
        toast({ title: '已提交索引任务，可在下方查看进度', variant: 'success' })
        setPathsText('')
        await loadSources()
      } else {
        toast({ title: j.message || '提交失败', variant: 'error' })
      }
    } catch (e) {
      console.error(e)
      toast({ title: '提交请求失败', variant: 'error' })
    } finally {
      setIndexing(false)
    }
  }, [pathsText, types, recursive, embedModel, loadSources])

  // ---------- 重新索引 / 取消 / 删除 ----------
  const reindex = useCallback(
    async (sourceId: string) => {
      try {
        const r = await fetch(`/api/rag/sources/${sourceId}/reindex`, { method: 'POST' })
        const j = await r.json()
        if (j.success) {
          toast({ title: '已重新提交索引', variant: 'success' })
          await loadSources()
        } else toast({ title: j.message || '操作失败', variant: 'error' })
      } catch {
        toast({ title: '请求失败', variant: 'error' })
      }
    },
    [loadSources]
  )

  const cancelIndex = useCallback(
    async (sourceId: string) => {
      try {
        await fetch(`/api/rag/sources/${sourceId}/cancel`, { method: 'POST' })
        await loadSources()
      } catch {
        /* ignore */
      }
    },
    [loadSources]
  )

  const deleteSource = useCallback(
    async (sourceId: string) => {
      try {
        const r = await fetch(`/api/rag/sources/${sourceId}`, { method: 'DELETE' })
        const j = await r.json()
        if (j.success) {
          toast({ title: '已删除索引源', variant: 'success' })
          setDocsBySource((prev) => {
            const n = { ...prev }
            delete n[sourceId]
            return n
          })
          if (expandedSource === sourceId) setExpandedSource(null)
          await loadSources()
        } else toast({ title: j.message || '删除失败', variant: 'error' })
      } catch {
        toast({ title: '删除请求失败', variant: 'error' })
      }
    },
    [loadSources, expandedSource]
  )

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  return (
    <div className="space-y-6">
      {/* 能力提示 */}
      {caps && (
        <div className="flex flex-wrap gap-2 text-xs">
          {caps.embeddingsConfigured ? (
            <Badge variant="secondary" className="bg-green-500/10 text-green-600 flex items-center gap-1">
              <KeyRound className="w-3 h-3" /> 向量检索可用
              {caps.embeddingModel ? `（${caps.embeddingModel}）` : ''}
            </Badge>
          ) : (
            <Badge variant="secondary" className="bg-yellow-500/10 text-yellow-600 flex items-center gap-1">
              <AlertCircle className="w-3 h-3" /> 未配置 LLM：将使用关键词检索
            </Badge>
          )}
          {caps.pdfAvailable ? (
            <Badge variant="secondary" className="bg-blue-500/10 text-blue-600">PDF 解析已启用</Badge>
          ) : (
            <Badge variant="secondary" className="bg-yellow-500/10 text-yellow-600">PDF 需 pip install pypdf</Badge>
          )}
        </div>
      )}

      {/* 添加索引源 */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-500/10 rounded-lg">
              <FolderSearch className="w-5 h-5 text-indigo-500" />
            </div>
            <div>
              <CardTitle>索引源</CardTitle>
              <CardDescription>
                填写一个或多个目标路径（文件或目录，每行一个），系统将自动抓取并切片索引；配置好后在 Chat 中开启「文档检索」即可基于这些文档问答。
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <textarea
            value={pathsText}
            onChange={(e) => setPathsText(e.target.value)}
            placeholder={'例如：\nD:\\papers\\thesis.pdf\nD:\\notes  (目录会递归扫描)'}
            className="w-full h-28 resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/40"
          />

          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">文件类型</span>
              {(['pdf', 'txt', 'md'] as const).map((t) => (
                <label key={t} className="flex items-center gap-1.5 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={types[t]}
                    onChange={(e) => setTypes((prev) => ({ ...prev, [t]: e.target.checked }))}
                    className="accent-primary"
                  />
                  {TYPE_LABELS[t]}
                </label>
              ))}
            </div>
            <label className="flex items-center gap-1.5 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={recursive}
                onChange={(e) => setRecursive(e.target.checked)}
                className="accent-primary"
              />
              递归子目录
            </label>
          </div>

          <div>
            <button
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
              onClick={() => setShowAdvanced((v) => !v)}
            >
              <KeyRound className="w-3 h-3" /> 高级（嵌入模型，可选）
            </button>
            {showAdvanced && (
              <div className="mt-2">
                <Input
                  value={embedModel}
                  onChange={(e) => setEmbedModel(e.target.value)}
                  placeholder="如 BAAI/bge-m3（留空用全局设置）"
                  className="text-sm"
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  指定用于生成向量的嵌入模型；留空则使用「模型与 API」中的全局嵌入模型。
                </p>
              </div>
            )}
          </div>

          <Button onClick={submitIndex} disabled={indexing}>
            {indexing ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Database className="w-4 h-4 mr-2" />}
            开始索引
          </Button>
        </CardContent>
      </Card>

      {/* 统计 */}
      {stats && (
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: '索引源', value: stats.sourceCount },
            { label: '文档', value: stats.docCount },
            { label: '切片', value: stats.chunkCount },
            { label: '向量', value: stats.vectorCount },
          ].map((s) => (
            <Card key={s.label}>
              <CardContent className="p-3 text-center">
                <div className="text-2xl font-display font-bold">{s.value}</div>
                <div className="text-xs text-muted-foreground">{s.label}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* 索引源列表 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="w-5 h-5" /> 已配置的索引源
            {isPolling && <Loader2 className="w-4 h-4 animate-spin text-blue-500" />}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {sources.length === 0 ? (
            <p className="text-sm text-muted-foreground py-6 text-center">
              暂无索引源，先在上方添加一个目标路径吧
            </p>
          ) : (
            <div className="space-y-3">
              {sources.map((src) => {
                const meta = STATUS_META[src.status] || STATUS_META.pending
                return (
                  <div key={src.id} className="rounded-lg border border-border p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium truncate">{src.name}</span>
                          <Badge variant="secondary" className={cn('flex items-center gap-1', meta.cls)}>
                            {src.status === 'indexing' && <Loader2 className="w-3 h-3 animate-spin" />}
                            {meta.label}
                          </Badge>
                          {src.embedMode === 'vector' ? (
                            <Badge variant="secondary" className="bg-blue-500/10 text-blue-600">向量</Badge>
                          ) : (
                            <Badge variant="secondary" className="bg-gray-500/10 text-gray-600">关键词</Badge>
                          )}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground break-all">
                          {src.targetPaths.join('  ·  ')}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {src.docCount} 文档 · {src.chunkCount} 切片
                          {src.error && (
                            <span className="ml-2 text-red-600">· {src.error}</span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        {src.status === 'indexing' ? (
                          <Button variant="ghost" size="sm" onClick={() => cancelIndex(src.id)}>
                            取消
                          </Button>
                        ) : (
                          <Button variant="ghost" size="sm" onClick={() => reindex(src.id)} title="重新索引">
                            <RefreshCw className="w-3.5 h-3.5" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-red-500"
                          onClick={() => deleteSource(src.id)}
                          title="删除"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </div>

                    {/* 展开文档列表 */}
                    <button
                      className="mt-2 text-xs text-muted-foreground hover:text-foreground"
                      onClick={() => setExpandedSource((v) => (v === src.id ? null : src.id))}
                    >
                      {expandedSource === src.id ? '收起文档' : `查看文档（${src.docCount}）`}
                    </button>
                    {expandedSource === src.id && docsBySource[src.id] && (
                      <div className="mt-2 max-h-48 overflow-y-auto rounded-md border border-border p-2 scrollbar-hide">
                        <div className="space-y-1.5">
                          {(docsBySource[src.id] || []).map((d) => (
                            <div key={d.id} className="flex items-center gap-2 text-sm">
                              <FileText className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
                              <span className="truncate flex-1">{d.fileName}</span>
                              <span className="text-xs text-muted-foreground shrink-0">
                                {d.pageCount}页 · {formatSize(d.fileSize)} · {d.chunkCount}片
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground flex items-center gap-1">
        <CheckCircle2 className="w-3.5 h-3.5" />
        问答检索请在 Chat Hub 中开启「文档检索」开关，回答会带 [n] 引用并溯源到这里的文档。
      </p>
    </div>
  )
}
