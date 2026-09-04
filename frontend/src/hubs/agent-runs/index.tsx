import { useState, useEffect, useCallback, useMemo } from 'react'
import { Header } from '@/components/layout/header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { MarkdownPreview } from '@/components/ui/markdown-editor'
import { cn } from '@/utils'
import { toast } from '@/components/ui/toast'
import { useNavigate } from 'react-router-dom'
import { RunGraph } from './components/RunGraph'
import { DAG_NAME_MAP } from '@/utils/agentNodes'
import {
  History,
  RefreshCw,
  Eye,
  XCircle,
  Loader2,
  CheckCircle2,
  X,
  AlertTriangle,
  Bot,
  ListTodo,
  FileCode,
  Sparkles,
  Clock,
  ShieldCheck,
  ShieldAlert,
  Check,
  RotateCcw,
  ListChecks,
  Wrench
} from 'lucide-react'

interface RunSummary {
  id: string
  spaceId: string
  projectId?: string
  requirement: string
  roles: string[]
  teamId?: string
  teamName?: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  errorMessage?: string
  resultSummary?: Record<string, any> | null
  createdAt: number
  startedAt?: number
  completedAt?: number
  runKind?: 'dag' | 'development'
  phase?: string
  iteration?: number
  maxIterations?: number
  teamSnapshot?: {
    nodes?: Array<{ id: string; name?: string; position?: { x: number; y: number } }>
    edges?: Array<{ id?: string; source: string; target: string }>
    outputNodeId?: string
  } | null
}

interface RunNode {
  nodeId: string
  name: string
  status: 'pending' | 'ready' | 'running' | 'completed' | 'failed' | 'skipped' | 'cancelled'
  textOutput?: string
  structuredOutput?: unknown
  errorMessage?: string
}

interface RunEvent {
  id: number
  runId: string
  type: string
  data: Record<string, any>
  createdAt: number
}

// 工具审批记录（来自 GET /runs/{id} 的 pendingApprovals 与 /approvals 历史）
interface ApprovalRecord {
  id: string
  runId: string
  spaceId: string
  tool: string
  nodeId?: string | null
  parameters: Record<string, any>
  status: 'pending' | 'approved' | 'denied' | 'timed_out' | 'cancelled'
  createdAt: number
  decidedAt?: number | null
}

// 可重放消息（来自 GET /runs/{id}/replay）
interface ReplayMessage {
  id: number
  runId: string
  phase: string
  round: number
  role: string
  message: Record<string, any>
  createdAt: number
}

const APPROVAL_STATUS_META: Record<ApprovalRecord['status'], { label: string; className: string }> = {
  pending: { label: '等待审批', className: 'bg-amber-500/10 text-amber-600' },
  approved: { label: '已批准', className: 'bg-green-500/10 text-green-600' },
  denied: { label: '已拒绝', className: 'bg-red-500/10 text-red-600' },
  timed_out: { label: '已超时', className: 'bg-gray-500/10 text-gray-600' },
  cancelled: { label: '已取消', className: 'bg-gray-500/10 text-gray-600' },
}

// 角色展示（与多 Agent 协作面板保持一致）
const ROLE_META: Record<string, { name: string; icon: any; color: string; bg: string }> = {
  architect: { name: '架构师', icon: Sparkles, color: 'text-purple-500', bg: 'bg-purple-500/10' },
  planner: { name: '规划师', icon: ListTodo, color: 'text-blue-500', bg: 'bg-blue-500/10' },
  developer: { name: '开发工程师', icon: FileCode, color: 'text-green-500', bg: 'bg-green-500/10' },
  reviewer: { name: '审查员', icon: CheckCircle2, color: 'text-orange-500', bg: 'bg-orange-500/10' },
  user: { name: '用户', icon: Bot, color: 'text-gray-500', bg: 'bg-gray-500/10' },
}

const STATUS_META: Record<RunSummary['status'], { label: string; className: string; icon: any }> = {
  pending: { label: '排队中', className: 'bg-gray-500/10 text-gray-600', icon: Clock },
  running: { label: '进行中', className: 'bg-blue-500/10 text-blue-600', icon: Loader2 },
  completed: { label: '已完成', className: 'bg-green-500/10 text-green-600', icon: CheckCircle2 },
  failed: { label: '失败', className: 'bg-red-500/10 text-red-600', icon: AlertTriangle },
  cancelled: { label: '已取消', className: 'bg-amber-500/10 text-amber-600', icon: XCircle },
}

function parsePrimaryOutput(output: unknown): { title?: string; markdown: string; tags: string[]; raw: string } {
  const raw = typeof output === 'string' ? output : JSON.stringify(output, null, 2)
  let obj: any = null
  if (typeof output === 'string') {
    try {
      const parsed = JSON.parse(output)
      if (parsed && typeof parsed === 'object') obj = parsed
    } catch { /* 纯文本，按 markdown 直接渲染 */ }
  } else if (output && typeof output === 'object') {
    obj = output as any
  }
  if (obj) {
    const markdown =
      (typeof obj.markdown === 'string' && obj.markdown) ||
      (typeof obj.content === 'string' && obj.content) ||
      raw
    return {
      title: typeof obj.title === 'string' ? obj.title : undefined,
      markdown,
      tags: Array.isArray(obj.tags) ? obj.tags.filter((t: unknown): t is string => typeof t === 'string') : [],
      raw,
    }
  }
  return { markdown: raw, tags: [], raw }
}

function relTime(ms?: number) {
  if (!ms) return '—'
  const diff = Date.now() - ms
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`
  return new Date(ms).toLocaleString()
}

export default function AgentRunsHub() {
  const navigate = useNavigate()
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<{ run: RunSummary; events: RunEvent[]; nodes: RunNode[]; primaryOutput?: unknown } | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailTab, setDetailTab] = useState<'events' | 'approvals' | 'replay'>('events')
  const [approvals, setApprovals] = useState<ApprovalRecord[]>([])
  const [approvalsLoading, setApprovalsLoading] = useState(false)
  const [replay, setReplay] = useState<ReplayMessage[]>([])
  const [replayLoading, setReplayLoading] = useState(false)
  const [replayLoaded, setReplayLoaded] = useState(false)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [savingNote, setSavingNote] = useState(false)
  const [showOutput, setShowOutput] = useState(false)

  const hasRunning = runs.some((r) => r.status === 'running' || r.status === 'pending')

  const loadRuns = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await fetch('/api/agent/runs?limit=100')
      const data = await resp.json()
      if (data.success) setRuns(data.runs || [])
    } catch {
      // 静默失败，下次轮询重试
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadRuns()
  }, [loadRuns])

  // 有在途运行时自动刷新列表
  useEffect(() => {
    if (!hasRunning) return
    const t = setInterval(loadRuns, 3000)
    return () => clearInterval(t)
  }, [hasRunning, loadRuns])

  // 拉取运行详情（不重置 tab 状态，供自动刷新复用）
  const fetchDetail = useCallback(async (id: string) => {
    try {
      const resp = await fetch(`/api/agent/runs/${id}`)
      const data = await resp.json()
      if (data.success) {
        setDetail({ run: data.run, events: data.events || [], nodes: data.nodes || [], primaryOutput: data.primaryOutput })
        // pendingApprovals 由 GET /runs/{id} 直接返回，审批面板再拉全量历史
        setApprovals(data.pendingApprovals || [])
        return true
      }
    } catch {
      // 交给上层处理
    }
    return false
  }, [])

  const openDetail = useCallback(async (id: string) => {
    setSelectedId(id)
    setShowOutput(false)
    setDetailLoading(true)
    setDetailTab('events')
    setReplayLoaded(false)
    setReplay([])
    setSelectedNodeId(null)
    try {
      const ok = await fetchDetail(id)
      if (!ok) toast({ title: '加载运行详情失败', variant: 'error' })
    } finally {
      setDetailLoading(false)
    }
  }, [fetchDetail])

  // 审批历史（全量，含已决策项）
  const loadApprovals = useCallback(async (id: string) => {
    setApprovalsLoading(true)
    try {
      const resp = await fetch(`/api/agent/runs/${id}/approvals`)
      const data = await resp.json()
      if (data.success) setApprovals(data.approvals || [])
    } catch {
      toast({ title: '加载审批记录失败', variant: 'error' })
    } finally {
      setApprovalsLoading(false)
    }
  }, [])

  // 可重放会话日志（按 phase/round 分组，懒加载）
  const loadReplay = useCallback(async (id: string) => {
    if (replayLoaded) return
    setReplayLoading(true)
    try {
      const resp = await fetch(`/api/agent/runs/${id}/replay`)
      const data = await resp.json()
      if (data.success) {
        setReplay(data.replay || [])
        setReplayLoaded(true)
      } else {
        toast({ title: data.message || '加载回放失败', variant: 'error' })
      }
    } catch {
      toast({ title: '加载回放失败', variant: 'error' })
    } finally {
      setReplayLoading(false)
    }
  }, [replayLoaded])

  // 工具审批决策
  const decideApproval = useCallback(async (runId: string, approvalId: string, approved: boolean) => {
    try {
      const resp = await fetch(`/api/agent/runs/${runId}/approvals/${approvalId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved })
      })
      const data = await resp.json()
      if (data.success) {
        toast({ title: approved ? '已批准工具执行' : '已拒绝工具调用', variant: 'info' })
        loadApprovals(runId)
      } else {
        toast({ title: data.message || '决策提交失败', variant: 'error' })
      }
    } catch {
      toast({ title: '决策提交失败', variant: 'error' })
    }
  }, [loadApprovals])

  // 详情抽屉里若仍在运行，自动刷新事件（不重置 tab）
  useEffect(() => {
    if (!selectedId) return
    const run = detail?.run
    if (!run || (run.status !== 'running' && run.status !== 'pending')) return
    const t = setInterval(() => fetchDetail(selectedId), 2000)
    return () => clearInterval(t)
  }, [selectedId, detail?.run, fetchDetail])

  const cancelRun = useCallback(async (id: string) => {
    try {
      await fetch(`/api/agent/runs/${id}/cancel`, { method: 'POST' })
      toast({ title: '已发送取消请求', variant: 'info' })
      loadRuns()
    } catch {
      toast({ title: '取消失败', variant: 'error' })
    }
  }, [loadRuns])

  // 保存主输出为 AI 笔记（仅 markdown 本体，tags 固定 Agent运行）
  const saveOutputAsNote = useCallback(async () => {
    if (detail?.primaryOutput == null || savingNote) return
    setSavingNote(true)
    try {
      const parsed = parsePrimaryOutput(detail.primaryOutput)
      const resp = await fetch('/api/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: parsed.title || detail.run.requirement.slice(0, 20) || 'Agent 运行成果',
          content: parsed.markdown,
          type: 'summary',
          tags: ['Agent运行'],
          aiGenerated: true,
        }),
      })
      const data = await resp.json()
      if (resp.ok && data.success) toast({ title: '已保存为 AI 笔记', variant: 'success' })
      else toast({ title: data.message || '保存笔记失败', variant: 'error' })
    } catch {
      toast({ title: '保存笔记失败', variant: 'error' })
    } finally {
      setSavingNote(false)
    }
  }, [detail, savingNote])

  return (
    <div className="flex flex-col h-screen">
      <Header title="运行历史" />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-5xl mx-auto space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              共 {runs.length} 条记录
              {hasRunning && <span className="ml-2 text-blue-600">· 有运行进行中，列表自动刷新</span>}
            </p>
            <Button variant="outline" size="sm" onClick={loadRuns} disabled={loading}>
              {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
              刷新
            </Button>
          </div>

          {runs.length === 0 ? (
            <Card>
              <CardContent className="py-16 flex flex-col items-center justify-center text-muted-foreground">
                <History className="w-12 h-12 mb-4 opacity-40" />
                <p>还没有后台运行记录</p>
                <p className="text-sm mt-1">在「软件开发」里点击「开始协作」即可发起一次多 Agent 规划</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-2">
              {runs.map((run) => {
                const st = STATUS_META[run.status]
                const StIcon = st.icon
                return (
                  <Card key={run.id} className="hover:border-primary/40 transition-colors">
                    <CardContent className="py-4 flex items-center gap-4">
                      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center shrink-0">
                        <Bot className="w-5 h-5 text-white" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <Badge className={cn('gap-1', st.className)}>
                            <StIcon className={cn('w-3 h-3', run.status === 'running' && 'animate-spin')} />
                            {st.label}
                          </Badge>
                          <span className="text-xs text-muted-foreground">{relTime(run.createdAt)}</span>
                        </div>
                        <p className="text-sm font-medium truncate">{run.requirement}</p>
                        {run.teamName && <div className="mt-1 text-xs font-medium text-primary">团队：{run.teamName}</div>}
                        {run.runKind === 'development' && <div className="mt-1 text-xs text-muted-foreground">
                          研发阶段：{run.phase || 'queued'} · 第 {run.iteration || 0}/{run.maxIterations || 12} 轮
                        </div>}
                        <div className="flex flex-wrap gap-1 mt-1">
                          {run.roles.map((role) => {
                            const m = ROLE_META[role] || ROLE_META.user
                            const Icon = m.icon
                            return (
                              <span key={role} className={cn('inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-md', m.bg, m.color)}>
                                <Icon className="w-3 h-3" />
                                {m.name}
                              </span>
                            )
                          })}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {run.runKind === 'development' && run.projectId && <Button size="sm" variant="outline"
                          onClick={(event) => { event.stopPropagation(); navigate(`/lab?tab=software&action=develop&projectId=${run.projectId}`) }}>
                          返回研发工作区
                        </Button>}
                        {(run.status === 'running' || run.status === 'pending') && (
                          <Button variant="ghost" size="sm" onClick={() => cancelRun(run.id)}>
                            <XCircle className="w-4 h-4 mr-1" />
                            取消
                          </Button>
                        )}
                        <Button variant="outline" size="sm" onClick={() => openDetail(run.id)}>
                          <Eye className="w-4 h-4 mr-1" />
                          查看
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* 详情弹窗（A2 全屏居中 92vh，小屏 95vw） */}
      {selectedId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setSelectedId(null)} />
          <div className="relative w-[96vw] max-w-[1400px] h-[94vh] glass rounded-2xl border border-border/50 shadow-2xl flex flex-col overflow-hidden min-h-0">
            <div className="flex items-center justify-between p-4 border-b shrink-0">
              <div className="min-w-0">
                <h3 className="font-medium truncate">运行详情</h3>
                <p className="text-xs text-muted-foreground mt-0.5">{detail?.run?.id}</p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={detail?.primaryOutput == null}
                  title={detail?.primaryOutput == null ? '主输出尚未生成' : '查看输出成果'}
                  onClick={() => setShowOutput(true)}
                >
                  查看输出成果
                </Button>
                <Button variant="ghost" size="icon" onClick={() => setSelectedId(null)}>
                  <X className="w-4 h-4" />
                </Button>
              </div>
            </div>

            {detailLoading && !detail ? (
              <div className="flex-1 flex items-center justify-center text-muted-foreground">
                <Loader2 className="w-6 h-6 animate-spin" />
              </div>
            ) : detail ? (
              <>
                <div className="grid gap-4 p-4 overflow-y-auto lg:grid-cols-[1.5fr_1fr] lg:overflow-hidden lg:flex-1 lg:min-h-0 min-h-0">
                  <div className="flex flex-col gap-2 lg:min-h-0 lg:overflow-hidden min-h-[320px]">
                  <div className="shrink-0 space-y-2">
                    {(() => {
                      const st = STATUS_META[detail.run.status]
                      const StIcon = st.icon
                      return (
                        <Badge className={cn('gap-1', st.className)}>
                          <StIcon className={cn('w-3 h-3', detail.run.status === 'running' && 'animate-spin')} />
                          {st.label}
                        </Badge>
                      )
                    })()}
                    <span className="text-xs text-muted-foreground">创建于 {relTime(detail.run.createdAt)}</span>
                  </div>
                  <p className="text-sm">{detail.run.requirement}</p>
                  {detail.run.teamName && <p className="text-xs font-medium text-primary">团队：{detail.run.teamName}</p>}
                  <div className="flex-1 min-h-0 lg:overflow-hidden flex flex-col">
                    <RunGraph
                      teamSnapshot={detail.run.teamSnapshot}
                      nodes={detail.nodes}
                      events={detail.events}
                      selectedNodeId={selectedNodeId}
                      onSelect={(id) => setSelectedNodeId(selectedNodeId === id ? null : id)}
                    />
                  </div>
                  {detail.nodes.length > 0 && (
                    <div id="run-nodes-block" className="flex flex-wrap gap-2 pt-2 shrink-0">
                      {detail.nodes.map(node => {
                        const displayName = node.name && node.name !== '用户'
                          ? node.name
                          : (DAG_NAME_MAP[node.nodeId] || node.nodeId)
                        return (
                          <button
                            key={node.nodeId}
                            onClick={() => setSelectedNodeId(selectedNodeId === node.nodeId ? null : node.nodeId)}
                            title="点击看分产物"
                            className={cn('rounded border px-2 py-1 text-xs text-left',
                              node.status === 'completed' && 'border-green-400 bg-green-500/10 text-green-700',
                              node.status === 'running' && 'border-blue-400 bg-blue-500/10 text-blue-700',
                              (node.status === 'failed' || node.status === 'skipped') && 'border-red-400 bg-red-500/10 text-red-700',
                              selectedNodeId === node.nodeId && 'ring-2 ring-primary/40')}>
                            {displayName} · {node.status}
                          </button>
                        )
                      })}
                    </div>
                  )}
                  {selectedNodeId && (() => {
                    const n = detail.nodes.find(x => x.nodeId === selectedNodeId)
                    if (!n) return null
                    return (
                      <div className="rounded-lg border p-3 text-xs space-y-1 shrink-0 max-h-[18vh] overflow-y-auto">
                        <p className="font-medium">节点分产物 · {n.name !== '用户' ? n.name : (DAG_NAME_MAP[n.nodeId] || n.nodeId)}</p>
                        {n.errorMessage && <p className="text-red-600">错误：{n.errorMessage}</p>}
                        {n.textOutput && <pre className="whitespace-pre-wrap break-words max-h-[22vh] overflow-y-auto bg-background p-2 rounded border">{n.textOutput.slice(0, 3000)}</pre>}
                        {n.structuredOutput != null && <pre className="whitespace-pre-wrap break-words max-h-[22vh] overflow-y-auto bg-background p-2 rounded border">{JSON.stringify(n.structuredOutput, null, 2).slice(0, 3000)}</pre>}
                      </div>
                    )
                  })()}
                  {detail.run.errorMessage && (
                    <p className="text-xs text-red-600">错误：{detail.run.errorMessage}</p>
                  )}
                  </div>
                  <div className="flex flex-col lg:min-h-0 lg:overflow-hidden min-h-[300px]">
                    {/* Tab 切换（右侧事件流） */}
                    <div className="flex items-center gap-1 px-1 border-b shrink-0">
                      {([
                        { key: 'events', label: '事件流', icon: ListChecks },
                        { key: 'approvals', label: '工具审批', icon: ShieldCheck },
                        { key: 'replay', label: '会话回放', icon: RotateCcw },
                      ] as const).map((tab) => {
                        const Icon = tab.icon
                        return (
                          <button
                            key={tab.key}
                            onClick={() => {
                              setDetailTab(tab.key)
                              if (tab.key === 'approvals') loadApprovals(selectedId)
                              if (tab.key === 'replay') loadReplay(selectedId)
                            }}
                            className={cn(
                              'flex items-center gap-1.5 px-3 py-2 text-sm rounded-t-lg border-b-2 transition-colors',
                              detailTab === tab.key
                                ? 'border-primary text-foreground font-medium'
                                : 'border-transparent text-muted-foreground hover:text-foreground'
                            )}
                          >
                            <Icon className="w-3.5 h-3.5" />
                            {tab.label}
                            {tab.key === 'approvals' && approvals.some(a => a.status === 'pending') && (
                              <span className="w-2 h-2 rounded-full bg-amber-500" />
                            )}
                          </button>
                        )
                      })}
                    </div>

                    {detailTab === 'events' && (
                      <ScrollArea className="flex-1 min-h-0" style={{ minHeight: 160 }}>
                        <div className="space-y-3 p-1">
                          {detail.events.length === 0 ? (
                            <p className="text-sm text-muted-foreground">暂无事件</p>
                          ) : (
                            detail.events.map((ev) => (
                              <EventRow
                                key={ev.id}
                                ev={ev}
                                nodesMap={Object.fromEntries(
                                  detail.nodes
                                    .filter((n) => n.name && n.name !== '用户')
                                    .map((n) => [n.nodeId, n.name]),
                                )}
                              />
                            ))
                          )}
                        </div>
                      </ScrollArea>
                    )}

                    {detailTab === 'approvals' && (
                      <ScrollArea className="flex-1 min-h-0" style={{ minHeight: 160 }}>
                        {approvalsLoading && approvals.length === 0 ? (
                          <div className="flex items-center justify-center py-10 text-muted-foreground">
                            <Loader2 className="w-5 h-5 animate-spin mr-2" />
                            加载中...
                          </div>
                        ) : approvals.length === 0 ? (
                          <p className="text-sm text-muted-foreground text-center py-10">
                            本次运行没有触发工具审批
                          </p>
                        ) : (
                          <div className="space-y-3">
                            {approvals.map((ap) => (
                              <ApprovalRow
                                key={ap.id}
                                approval={ap}
                                runId={selectedId}
                                onDecide={decideApproval}
                              />
                            ))}
                          </div>
                        )}
                      </ScrollArea>
                    )}

                    {detailTab === 'replay' && (
                      <ScrollArea className="flex-1 min-h-0" style={{ minHeight: 160 }}>
                        {replayLoading ? (
                          <div className="flex items-center justify-center py-10 text-muted-foreground">
                            <Loader2 className="w-5 h-5 animate-spin mr-2" />
                            加载会话日志...
                          </div>
                        ) : replay.length === 0 ? (
                          <div className="text-center py-10">
                            <RotateCcw className="w-8 h-8 mx-auto mb-2 text-muted-foreground/40" />
                            <p className="text-sm text-muted-foreground">暂无回放记录</p>
                            <p className="text-xs text-muted-foreground mt-1">
                              运行中每轮「模型实际看到的消息」会落库，完成后可完整回放定位问题
                            </p>
                          </div>
                        ) : (
                          <ReplayPanel messages={replay} />
                        )}
                      </ScrollArea>
                    )}
                  </div>
                </div>

              </>
            ) : null}
          </div>

          {/* 输出成果二级悬浮窗（保存后不自动关闭） */}
          {showOutput && detail && (
            <div className="absolute inset-0 z-[60] flex items-center justify-center p-4">
              <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowOutput(false)} />
              <div className="relative w-[90vw] max-w-3xl max-h-[85vh] glass rounded-2xl border border-border/50 shadow-2xl flex flex-col overflow-hidden">
                <div className="flex items-center justify-between p-4 border-b shrink-0">
                  <h4 className="font-medium">输出成果</h4>
                  <Button variant="ghost" size="icon" onClick={() => setShowOutput(false)}>
                    <X className="w-4 h-4" />
                  </Button>
                </div>
                <div className="p-4 overflow-y-auto flex-1 min-h-0">
                  {detail.primaryOutput != null ? (
                    (() => {
                      const parsed = parsePrimaryOutput(detail.primaryOutput)
                      return (
                        <>
                          {parsed.title && <p className="text-sm font-semibold mb-2">{parsed.title}</p>}
                          <MarkdownPreview content={parsed.markdown.slice(0, 8000)} />
                          {parsed.tags.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-2">
                              {parsed.tags.map((t) => (
                                <Badge key={t} variant="secondary" className="text-[10px]">{t}</Badge>
                              ))}
                            </div>
                          )}
                          <details className="mt-2">
                            <summary className="text-xs text-muted-foreground cursor-pointer">查看原始输出</summary>
                            <pre className="text-xs whitespace-pre-wrap break-words max-h-40 overflow-y-auto mt-1">
                              {parsed.raw.slice(0, 2000)}
                            </pre>
                          </details>
                        </>
                      )
                    })()
                  ) : (
                    <p className="text-sm text-muted-foreground">主输出尚未生成，可去节点详情看分产物。</p>
                  )}
                </div>
                <div className="flex items-center justify-end gap-2 p-4 border-t shrink-0">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      const parsed = detail.primaryOutput != null ? parsePrimaryOutput(detail.primaryOutput) : null
                      navigator.clipboard?.writeText(parsed?.markdown || '')
                      toast({ title: '已复制输出成果', variant: 'success' })
                    }}
                    disabled={detail.primaryOutput == null}
                  >
                    复制
                  </Button>
                  <Button size="sm" onClick={saveOutputAsNote} disabled={savingNote || detail.primaryOutput == null}>
                    {savingNote ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : null}
                    保存为 AI 笔记
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function EventRow({ ev, nodesMap }: { ev: RunEvent; nodesMap?: Record<string, string> }) {
  const d = ev.data || {}
  const role = (d.agent || d.phase || d.nodeId || '') as string
  const resolvedName =
    (nodesMap?.[role] && nodesMap[role] !== '用户' ? nodesMap[role] : null) ||
    (DAG_NAME_MAP[role] && DAG_NAME_MAP[role] !== '用户' ? DAG_NAME_MAP[role] : null) ||
    ROLE_META[role]?.name ||
    (role && role !== 'user' ? role : '系统')
  const m = ROLE_META[role] || ROLE_META.user
  const Icon = m.icon
  let text = ''
  let statusBadge: { label: string; className: string } | null = null

  switch (ev.type) {
    case 'phase_start':
      text = `阶段开始 · ${resolvedName}${d.message ? `：${d.message}` : ''}`
      break
    case 'start':
      text = `${resolvedName} 启动${d.message ? `：${d.message}` : ''}`
      break
    case 'progress':
      text = `${resolvedName} · ${d.step || ''}${typeof d.progress === 'number' ? `（${d.progress}%）` : ''}`
      break
    case 'complete':
      text = `${resolvedName} 阶段产出完成`
      break
    case 'run_complete':
      text = '全部阶段完成 ✅'
      break
    case 'run_cancelled':
      text = `运行已取消${d.message ? `：${d.message}` : ''}`
      break
    case 'error':
      text = `错误：${d.message || ''}`
      break
    case 'tool_approval': {
      const status = d.status as string
      const st = APPROVAL_STATUS_META[status as keyof typeof APPROVAL_STATUS_META]
      text = `工具审批 · ${d.tool || ''}${d.message ? `：${d.message}` : ''}`
      statusBadge = st || { label: status, className: 'bg-gray-500/10 text-gray-600' }
      break
    }
    case 'context_compressed':
      text = `上下文管理 · ${d.message || '历史已压缩'}`
      statusBadge = { label: '压缩', className: 'bg-blue-500/10 text-blue-600' }
      break
    default:
      text = JSON.stringify(d).slice(0, 80)
  }

  return (
    <div className="flex gap-3 p-3 rounded-lg bg-muted/40 border border-border/50">
      <div className={cn('w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0', m.bg)}>
        <Icon className={cn('w-3.5 h-3.5', m.color)} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="text-sm">{text}</p>
          {statusBadge && (
            <span className={cn('inline-flex items-center px-1.5 py-0.5 rounded text-xs shrink-0', statusBadge.className)}>
              {statusBadge.label}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">{relTime(ev.createdAt)}</p>
      </div>
    </div>
  )
}

// 审批记录行：pending 提供决策按钮，终态展示结果
function ApprovalRow({
  approval,
  runId,
  onDecide,
}: {
  approval: ApprovalRecord
  runId: string
  onDecide: (runId: string, approvalId: string, approved: boolean) => void
}) {
  const st = APPROVAL_STATUS_META[approval.status]
  const isPending = approval.status === 'pending'
  return (
    <div className="p-3 rounded-lg bg-muted/40 border border-border/50">
      <div className="flex items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-2 min-w-0">
          {isPending ? (
            <ShieldAlert className="w-4 h-4 text-amber-500 shrink-0" />
          ) : (
            <ShieldCheck className={cn('w-4 h-4 shrink-0', approval.status === 'approved' ? 'text-green-500' : 'text-muted-foreground')} />
          )}
          <code className="text-xs font-mono px-1.5 py-0.5 rounded bg-background border border-border/60">
            {approval.tool}
          </code>
          {approval.nodeId && <Badge variant="outline" className="text-[10px]">节点 {approval.nodeId}</Badge>}
          <span className={cn('inline-flex items-center px-1.5 py-0.5 rounded text-xs', st.className)}>
            {st.label}
          </span>
        </div>
        <span className="text-xs text-muted-foreground shrink-0">{relTime(approval.createdAt)}</span>
      </div>
      <pre className="mt-1 p-2 rounded-md bg-background/80 border border-border/50 text-xs font-mono text-muted-foreground overflow-x-auto max-h-32">
        {JSON.stringify(approval.parameters, null, 2)}
      </pre>
      {isPending && (
        <div className="flex items-center gap-2 mt-2">
          <Button
            size="sm"
            className="gap-1 bg-green-500 hover:bg-green-600 text-white"
            onClick={() => onDecide(runId, approval.id, true)}
          >
            <Check className="w-3.5 h-3.5" />
            允许执行
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="gap-1 text-red-600 border-red-300 hover:bg-red-50"
            onClick={() => onDecide(runId, approval.id, false)}
          >
            <X className="w-3.5 h-3.5" />
            拒绝
          </Button>
        </div>
      )}
    </div>
  )
}

// 会话回放面板：按 (phase, round) 分组渲染模型实际看到的消息
function ReplayPanel({ messages }: { messages: ReplayMessage[] }) {
  const groups = useMemo(() => {
    const map = new Map<string, ReplayMessage[]>()
    for (const msg of messages) {
      const key = `${msg.phase}__${msg.round}`
      const list = map.get(key)
      if (list) list.push(msg)
      else map.set(key, [msg])
    }
    return Array.from(map.entries()).sort((a, b) => {
      const [pa, ra] = a[0].split('__')
      const [pb, rb] = b[0].split('__')
      return pa.localeCompare(pb) || Number(ra) - Number(rb)
    })
  }, [messages])

  if (groups.length === 0) return null

  return (
    <div className="space-y-4">
      {groups.map(([key, msgs]) => {
        const [phase, round] = key.split('__')
        const meta = ROLE_META[phase] || ROLE_META.user
        const PhaseIcon = meta.icon
        const phaseName = DAG_NAME_MAP[phase] || (phase === 'user' ? '用户' : meta.name === '用户' && phase !== 'user' ? phase : meta.name)
        return (
          <div key={key} className="space-y-2">
            <div className="flex items-center gap-2 sticky top-0 bg-background/95 backdrop-blur py-1">
              <div className={cn('w-6 h-6 rounded-full flex items-center justify-center', meta.bg)}>
                <PhaseIcon className={cn('w-3.5 h-3.5', meta.color)} />
              </div>
              <span className={cn('text-xs font-medium', meta.color)}>{phaseName}</span>
              <span className="text-xs text-muted-foreground">第 {round} 轮</span>
              <span className="text-[10px] text-muted-foreground/60">· {msgs.length} 条消息</span>
            </div>
            <div className="space-y-1.5">
              {msgs.map((m) => (
                <ReplayMessageRow key={m.id} msg={m} />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ReplayMessageRow({ msg }: { msg: ReplayMessage }) {
  const body = msg.message || {}
  const role = body.role || msg.role || 'user'
  const roleLabel: Record<string, string> = {
    system: '系统',
    user: '用户',
    assistant: '助手',
    tool: '工具',
  }
  const roleColor: Record<string, string> = {
    system: 'text-gray-500 bg-gray-500/10',
    user: 'text-blue-600 bg-blue-500/10',
    assistant: 'text-purple-600 bg-purple-500/10',
    tool: 'text-green-600 bg-green-500/10',
  }

  // tool_calls（assistant 消息）与 tool 结果分别渲染
  const toolCalls = Array.isArray(body.tool_calls) ? body.tool_calls : []
  const hasContent = typeof body.content === 'string' && body.content.trim().length > 0
  const toolResult = role === 'tool' ? body.content : null

  return (
    <div className="p-2.5 rounded-lg bg-background border border-border/40">
      <div className="flex items-center gap-2 mb-1">
        <span className={cn('inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium', roleColor[role] || roleColor.user)}>
          {roleLabel[role] || role}
        </span>
        {body.name && (
          <code className="text-[10px] font-mono text-muted-foreground">{body.name}</code>
        )}
      </div>
      {hasContent && (
        <p className="text-xs text-foreground/90 whitespace-pre-wrap break-words">{body.content}</p>
      )}
      {toolResult && (
        <p className="text-xs text-green-700 bg-green-500/5 rounded p-1.5 border border-green-500/15 whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
          {typeof toolResult === 'string' ? toolResult : JSON.stringify(toolResult)}
        </p>
      )}
      {toolCalls.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-1">
          {toolCalls.map((tc: any, i: number) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-700 border border-amber-500/20"
            >
              <Wrench className="w-3 h-3" />
              {tc.function?.name || 'tool_call'}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
