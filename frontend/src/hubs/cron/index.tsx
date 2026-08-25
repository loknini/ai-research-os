import { useState, useEffect, useCallback } from 'react'
import { Header } from '@/components/layout/header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/utils'
import { toast } from '@/components/ui/toast'
import {
  Clock,
  Plus,
  RefreshCw,
  Play,
  Trash2,
  Power,
  History,
  X,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Terminal,
  Bot,
  FileText,
} from 'lucide-react'
import type { CronJob, CronRunHistory } from '@/types'
import {
  fetchCronJobs,
  createCronJob,
  toggleCronJob,
  runCronJob,
  deleteCronJob,
  fetchCronHistory,
} from '@/services/cronApi'

const JOB_TYPE_META: Record<string, { label: string; icon: any; color: string }> = {
  command: { label: '命令', icon: Terminal, color: 'text-gray-600' },
  agent_run: { label: 'Agent 管线', icon: Bot, color: 'text-purple-500' },
  arxiv_fetch: { label: '论文抓取', icon: FileText, color: 'text-blue-500' },
}

const STATUS_META: Record<string, { label: string; className: string; icon: any }> = {
  success: { label: '成功', className: 'bg-green-500/10 text-green-600', icon: CheckCircle2 },
  failed: { label: '失败', className: 'bg-red-500/10 text-red-600', icon: AlertTriangle },
  timeout: { label: '超时', className: 'bg-amber-500/10 text-amber-600', icon: Clock },
  error: { label: '异常', className: 'bg-red-500/10 text-red-600', icon: XCircle },
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

function fmtDuration(ms: number) {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export default function CronHub() {
  const [jobs, setJobs] = useState<CronJob[]>([])
  const [loading, setLoading] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [historyJobId, setHistoryJobId] = useState<string | null>(null)
  const [history, setHistory] = useState<CronRunHistory[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchCronJobs()
      setJobs(data)
    } catch (e: any) {
      toast({ title: '加载失败', description: e.message, variant: 'error' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    // 每 30 秒刷新一次（调度器更新 nextRun / lastRun）
    const timer = setInterval(load, 30_000)
    return () => clearInterval(timer)
  }, [load])

  const handleToggle = async (job: CronJob) => {
    try {
      await toggleCronJob(job.id)
      toast({ title: job.enabled ? '已暂停' : '已启用', description: job.name })
      load()
    } catch (e: any) {
      toast({ title: '操作失败', description: e.message, variant: 'error' })
    }
  }

  const handleRun = async (job: CronJob) => {
    try {
      const result = await runCronJob(job.id)
      toast({
        title: result.status === 'success' ? '运行完成' : '运行异常',
        description: result.output.slice(0, 200),
        variant: result.status === 'success' ? 'success' : 'error',
      })
      load()
    } catch (e: any) {
      toast({ title: '运行失败', description: e.message, variant: 'error' })
    }
  }

  const handleDelete = async (job: CronJob) => {
    if (!confirm(`确认删除任务「${job.name}」？`)) return
    try {
      await deleteCronJob(job.id)
      toast({ title: '已删除', description: job.name })
      load()
    } catch (e: any) {
      toast({ title: '删除失败', description: e.message, variant: 'error' })
    }
  }

  const handleHistory = async (jobId: string) => {
    setHistoryJobId(jobId)
    try {
      const data = await fetchCronHistory(jobId)
      setHistory(data)
    } catch (e: any) {
      toast({ title: '历史加载失败', description: e.message, variant: 'error' })
    }
  }

  return (
    <div className="h-screen flex flex-col">
      <Header title="定时任务" />
      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-5xl mx-auto">
          {/* 标题栏 */}
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-bold tracking-tight">定时任务</h1>
              <p className="text-sm text-muted-foreground mt-1">
                定时触发 Agent 管线、论文抓取或自定义命令
              </p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={load} disabled={loading}>
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                刷新
              </Button>
              <Button size="sm" onClick={() => setShowCreate(true)}>
                <Plus className="w-4 h-4" />
                新建任务
              </Button>
            </div>
          </div>

          {/* 任务列表 */}
          {jobs.length === 0 && !loading ? (
            <Card className="glass">
              <CardContent className="flex flex-col items-center justify-center py-16 text-center">
                <Clock className="w-12 h-12 text-muted-foreground/40 mb-3" />
                <p className="text-muted-foreground">还没有定时任务</p>
                <Button variant="outline" size="sm" className="mt-4" onClick={() => setShowCreate(true)}>
                  <Plus className="w-4 h-4 mr-1" /> 创建第一个任务
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {jobs.map((job) => {
                const meta = JOB_TYPE_META[job.jobType] || JOB_TYPE_META.command
                const Icon = meta.icon
                return (
                  <Card key={job.id} className={cn('glass', !job.enabled && 'opacity-60')}>
                    <CardContent className="p-4">
                      <div className="flex items-start justify-between gap-4">
                        {/* 左侧：任务信息 */}
                        <div className="flex items-start gap-3 flex-1 min-w-0">
                          <div className={cn('mt-0.5', meta.color)}>
                            <Icon className="w-5 h-5" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-semibold truncate">{job.name}</span>
                              <Badge variant="secondary" className="text-xs">
                                {meta.label}
                              </Badge>
                              <Badge variant="outline" className="text-xs font-mono">
                                {job.schedule}
                              </Badge>
                              {!job.enabled && (
                                <Badge variant="outline" className="text-xs text-muted-foreground">
                                  已暂停
                                </Badge>
                              )}
                            </div>
                            {job.description && (
                              <p className="text-sm text-muted-foreground mt-1 truncate">{job.description}</p>
                            )}
                            <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                              <span>上次运行: {relTime(job.lastRun)}</span>
                              <span>下次运行: {relTime(job.nextRun)}</span>
                              <span>已执行 {job.runCount} 次</span>
                            </div>
                          </div>
                        </div>

                        {/* 右侧：操作按钮 */}
                        <div className="flex items-center gap-1 shrink-0">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            title="查看历史"
                            onClick={() => handleHistory(job.id)}
                          >
                            <History className="w-4 h-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            title="立即运行"
                            onClick={() => handleRun(job)}
                          >
                            <Play className="w-4 h-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            title={job.enabled ? '暂停' : '启用'}
                            onClick={() => handleToggle(job)}
                          >
                            <Power className={cn('w-4 h-4', job.enabled ? 'text-green-500' : 'text-muted-foreground')} />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-red-500 hover:text-red-600"
                            title="删除"
                            onClick={() => handleDelete(job)}
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* 创建任务弹窗 */}
      {showCreate && (
        <CreateJobDialog
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false)
            load()
          }}
        />
      )}

      {/* 运行历史抽屉 */}
      {historyJobId && (
        <HistoryDrawer
          jobId={historyJobId}
          jobName={jobs.find((j) => j.id === historyJobId)?.name || ''}
          history={history}
          onClose={() => setHistoryJobId(null)}
        />
      )}
    </div>
  )
}

// ==================== 创建任务弹窗 ====================
function CreateJobDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: () => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [schedule, setSchedule] = useState('daily')
  const [jobType, setJobType] = useState<'command' | 'agent_run' | 'arxiv_fetch'>('command')
  const [command, setCommand] = useState('')
  // agent_run payload
  const [requirement, setRequirement] = useState('')
  const [roles, setRoles] = useState('')
  // arxiv_fetch payload
  const [query, setQuery] = useState('cat:cs.CV')
  const [keywords, setKeywords] = useState('')
  const [maxResults, setMaxResults] = useState('10')
  const [submitting, setSubmitting] = useState(false)

  const SCHEDULE_PRESETS = [
    { value: 'hourly', label: '每小时' },
    { value: 'daily', label: '每天 8:00' },
    { value: 'weekly', label: '每周一 8:00' },
    { value: 'every_minute', label: '每分钟（测试）' },
    { value: '0 8 * * 1-5', label: '工作日 8:00' },
  ]

  const handleSubmit = async () => {
    if (!name.trim()) {
      toast({ title: '请输入任务名称', variant: 'error' })
      return
    }
    if (!schedule.trim()) {
      toast({ title: '请输入调度表达式', variant: 'error' })
      return
    }

    const body: {
      name: string
      description?: string
      schedule: string
      command?: string
      jobType: string
      payload?: Record<string, any> | null
      enabled?: boolean
    } = { name, description, schedule, jobType }
    if (jobType === 'command') {
      if (!command.trim()) {
        toast({ title: '请输入要执行的命令', variant: 'error' })
        return
      }
      body.command = command
    } else if (jobType === 'agent_run') {
      if (!requirement.trim()) {
        toast({ title: '请输入 Agent 需求描述', variant: 'error' })
        return
      }
      body.payload = {
        requirement,
        roles: roles.trim() ? roles.split(',').map((r) => r.trim()) : undefined,
      }
    } else if (jobType === 'arxiv_fetch') {
      body.payload = {
        query,
        keywords: keywords.trim() ? keywords.split(',').map((k) => k.trim()) : [],
        max: parseInt(maxResults) || 10,
      }
    }

    setSubmitting(true)
    try {
      await createCronJob(body)
      toast({ title: '任务已创建', description: name })
      onCreated()
    } catch (e: any) {
      toast({ title: '创建失败', description: e.message, variant: 'error' })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <Card
        className="glass w-full max-w-lg max-h-[85vh] overflow-auto mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <CardContent className="p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold">新建定时任务</h2>
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
              <X className="w-4 h-4" />
            </Button>
          </div>

          {/* 任务名称 */}
          <div>
            <label className="text-sm font-medium mb-1.5 block">任务名称</label>
            <input
              className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如：每日 arXiv 论文抓取"
            />
          </div>

          {/* 描述 */}
          <div>
            <label className="text-sm font-medium mb-1.5 block">描述（可选）</label>
            <input
              className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="任务说明"
            />
          </div>

          {/* 任务类型 */}
          <div>
            <label className="text-sm font-medium mb-1.5 block">任务类型</label>
            <div className="grid grid-cols-3 gap-2">
              {(['command', 'agent_run', 'arxiv_fetch'] as const).map((t) => {
                const meta = JOB_TYPE_META[t]
                const Icon = meta.icon
                return (
                  <button
                    key={t}
                    onClick={() => setJobType(t)}
                    className={cn(
                      'flex flex-col items-center gap-1 rounded-lg border p-3 text-xs transition-colors',
                      jobType === t
                        ? 'border-primary bg-primary/5 text-primary'
                        : 'hover:bg-muted/50'
                    )}
                  >
                    <Icon className="w-4 h-4" />
                    {meta.label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* 调度表达式 */}
          <div>
            <label className="text-sm font-medium mb-1.5 block">调度表达式</label>
            <input
              className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm font-mono outline-none focus:ring-2 focus:ring-primary/30"
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              placeholder="如 daily / 0 8 * * * / */30 * * * *"
            />
            <div className="flex flex-wrap gap-1.5 mt-2">
              {SCHEDULE_PRESETS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => setSchedule(p.value)}
                  className="rounded-full border px-2.5 py-0.5 text-xs hover:bg-muted/50"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* 类型特定参数 */}
          {jobType === 'command' && (
            <div>
              <label className="text-sm font-medium mb-1.5 block">Shell 命令</label>
              <input
                className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm font-mono outline-none focus:ring-2 focus:ring-primary/30"
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                placeholder="如 echo hello"
              />
            </div>
          )}

          {jobType === 'agent_run' && (
            <>
              <div>
                <label className="text-sm font-medium mb-1.5 block">Agent 需求</label>
                <textarea
                  className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30 min-h-[80px]"
                  value={requirement}
                  onChange={(e) => setRequirement(e.target.value)}
                  placeholder="描述要交给多角色管线处理的需求"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-1.5 block">角色（逗号分隔，可选）</label>
                <input
                  className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm font-mono outline-none focus:ring-2 focus:ring-primary/30"
                  value={roles}
                  onChange={(e) => setRoles(e.target.value)}
                  placeholder="architect,planner,reviewer"
                />
              </div>
            </>
          )}

          {jobType === 'arxiv_fetch' && (
            <>
              <div>
                <label className="text-sm font-medium mb-1.5 block">arXiv 查询</label>
                <input
                  className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm font-mono outline-none focus:ring-2 focus:ring-primary/30"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="cat:cs.CV"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-sm font-medium mb-1.5 block">关键词（逗号分隔）</label>
                  <input
                    className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
                    value={keywords}
                    onChange={(e) => setKeywords(e.target.value)}
                    placeholder="diffusion,controlnet"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium mb-1.5 block">最大篇数</label>
                  <input
                    className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
                    value={maxResults}
                    onChange={(e) => setMaxResults(e.target.value)}
                    type="number"
                  />
                </div>
              </div>
            </>
          )}

          {/* 操作 */}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose}>
              取消
            </Button>
            <Button onClick={handleSubmit} disabled={submitting}>
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              创建
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ==================== 运行历史抽屉 ====================
function HistoryDrawer({
  jobName,
  history,
  onClose,
}: {
  jobId: string
  jobName: string
  history: CronRunHistory[]
  onClose: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-md h-full overflow-auto bg-background border-l"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-background/80 backdrop-blur-md border-b px-5 py-4 flex items-center justify-between">
          <div>
            <h2 className="font-bold">执行历史</h2>
            <p className="text-xs text-muted-foreground">{jobName}</p>
          </div>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
        </div>

        <div className="p-5 space-y-3">
          {history.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <History className="w-10 h-10 mx-auto mb-2 opacity-40" />
              <p className="text-sm">暂无执行记录</p>
            </div>
          ) : (
            history.map((h) => {
              const meta = STATUS_META[h.status] || STATUS_META.error
              const Icon = meta.icon
              return (
                <Card key={h.id} className="glass">
                  <CardContent className="p-3">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Icon className={cn('w-4 h-4', meta.className.split(' ')[1])} />
                        <Badge className={meta.className}>{meta.label}</Badge>
                      </div>
                      <span className="text-xs text-muted-foreground">{fmtDuration(h.durationMs)}</span>
                    </div>
                    <p className="text-xs text-muted-foreground mb-1">{relTime(h.startedAt)}</p>
                    {h.output && (
                      <pre className="text-xs bg-muted/50 rounded p-2 mt-2 overflow-auto max-h-32 whitespace-pre-wrap break-all">
                        {h.output}
                      </pre>
                    )}
                  </CardContent>
                </Card>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
