import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Code2, Loader2, Play, RefreshCw, Square, GitCompare } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import type { SoftwareProject } from '@/types'
import {
  applyDevelopmentRun, cancelDevelopmentRun, continueDevelopmentRun,
  createDevelopmentRun, fetchDevelopmentDiff, fetchDevelopmentRun,
  fetchDevelopmentRuns, validateWorkspace
} from '../services/projectsApi'

interface TeamOption { id: string; name: string; workflowType?: string; acceptedContexts: string[] }
interface DevelopmentRun {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  phase?: string
  iteration?: number
  maxIterations?: number
  budgetUsedMs?: number
  errorMessage?: string
  requirement: string
  teamName?: string
}

const PHASE_LABELS: Record<string, string> = {
  queued: '等待领取', preparing: '准备隔离工作区', analyzing: '分析', implementing: '实现',
  testing: '测试', reviewing: '审查', awaiting_apply: '等待应用', applied: '已应用',
  budget_exhausted: '预算耗尽', conflict: '应用冲突', failed: '失败'
}

export function DevelopmentWorkspace({ project, defaultTeamId, autoOpen = false }: {
  project: SoftwareProject
  defaultTeamId?: string
  autoOpen?: boolean
}) {
  const [open, setOpen] = useState(autoOpen)
  const [goal, setGoal] = useState('')
  const [criteria, setCriteria] = useState('')
  const [teams, setTeams] = useState<TeamOption[]>([])
  const [teamId, setTeamId] = useState(defaultTeamId || 'builtin-software-development')
  const [workspace, setWorkspace] = useState<any>(null)
  const [runs, setRuns] = useState<DevelopmentRun[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [diff, setDiff] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [maxIterations, setMaxIterations] = useState(12)
  const [maxDurationMinutes, setMaxDurationMinutes] = useState(60)

  useEffect(() => { if (autoOpen) setOpen(true) }, [autoOpen])
  useEffect(() => { if (defaultTeamId) setTeamId(defaultTeamId) }, [defaultTeamId])

  const refreshRuns = useCallback(async () => {
    try {
      const values = await fetchDevelopmentRuns(project.id)
      setRuns(values)
      if (!activeId && values[0]) setActiveId(values[0].id)
    } catch (error) {
      toast({ title: '研发历史加载失败', description: String(error), variant: 'error' })
    }
  }, [activeId, project.id])

  useEffect(() => {
    if (!open) return
    void validateWorkspace(project.id).then(setWorkspace).catch(error =>
      toast({ title: '工作区不可用', description: String(error), variant: 'error' }))
    void fetch('/api/agent/teams').then(response => response.json()).then(data =>
      setTeams((data.teams || []).filter((team: TeamOption) =>
        team.workflowType === 'development' && team.acceptedContexts?.includes('software_project'))))
    void refreshRuns()
  }, [open, project.id, refreshRuns])

  useEffect(() => {
    if (!activeId || !open) return
    let alive = true
    const load = async () => {
      try {
        const value = await fetchDevelopmentRun(activeId)
        if (!alive) return
        setDetail(value)
        if (value.run.phase === 'awaiting_apply' || value.run.phase === 'conflict' || value.run.phase === 'applied') {
          setDiff(await fetchDevelopmentDiff(activeId))
        }
      } catch (error) {
        if (alive) console.error(error)
      }
    }
    void load()
    const timer = window.setInterval(() => {
      const status = detail?.run?.status
      if (status === 'pending' || status === 'running' || !status) void load()
    }, 1500)
    return () => { alive = false; window.clearInterval(timer) }
  }, [activeId, open, detail?.run?.status])

  const active = detail?.run as DevelopmentRun | undefined
  const elapsed = Math.round((active?.budgetUsedMs || 0) / 60000)
  const commandArtifacts = useMemo(() => (detail?.artifacts || []).filter((item: any) => item.kind === 'command_log'), [detail])

  const start = async () => {
    if (!goal.trim()) return
    setBusy(true)
    try {
      const id = await createDevelopmentRun(project.id, {
        goal: goal.trim(), teamId,
        successCriteria: criteria.split('\n').map(value => value.trim()).filter(Boolean),
        maxIterations, maxDurationMinutes,
        authorization: { workspaceWrites: true, verificationCommands: true }
      })
      setActiveId(id); setDetail(null); setDiff(null); await refreshRuns()
      window.dispatchEvent(new CustomEvent('development-run-changed'))
      toast({ title: '研发运行已启动', variant: 'success' })
    } catch (error) {
      toast({ title: '启动失败', description: String(error), variant: 'error' })
    } finally { setBusy(false) }
  }

  if (!open) return <Button className="w-full" variant="outline" onClick={() => setOpen(true)}>
    <Code2 className="mr-2 h-4 w-4" />Agent 研发工作区
  </Button>

  return <div className="space-y-3 rounded-lg border bg-background p-3">
    <div className="flex items-center justify-between">
      <div className="font-semibold flex items-center gap-2"><Code2 className="h-4 w-4" />Agent 研发工作区</div>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>收起</Button>
    </div>
    <div className="rounded border bg-muted/30 p-2 text-xs">
      <div>{workspace?.kind === 'git' ? 'Git worktree' : workspace?.kind === 'directory' ? '受控目录副本' : '受管理 Git 项目'}</div>
      <div className="truncate text-muted-foreground">{workspace?.path || project.localPath || '首次运行时创建'}</div>
      {workspace?.warnings?.map((warning: string) => <div key={warning} className="text-amber-600">{warning}</div>)}
      <div className="mt-1">验证：{workspace?.commands?.map((command: string[]) => command.join(' ')).join('；') || '待 Agent 补充'}</div>
    </div>
    <textarea className="min-h-20 w-full rounded border bg-background p-2 text-sm" value={goal}
      onChange={event => setGoal(event.target.value)} placeholder="描述需要 Agent 实际完成的研发目标……" />
    <textarea className="min-h-14 w-full rounded border bg-background p-2 text-xs" value={criteria}
      onChange={event => setCriteria(event.target.value)} placeholder="可选成功标准，每行一项" />
    <select className="h-9 w-full rounded border bg-background px-2 text-sm" value={teamId}
      onChange={event => setTeamId(event.target.value)}>
      {teams.map(team => <option key={team.id} value={team.id}>{team.name}</option>)}
    </select>
    <div className="grid grid-cols-2 gap-2">
      <label className="text-xs">最大轮数
        <Input className="mt-1" type="number" min={1} max={50} value={maxIterations}
          onChange={event => setMaxIterations(Math.min(50, Math.max(1, Number(event.target.value) || 1)))} />
      </label>
      <label className="text-xs">最长分钟
        <Input className="mt-1" type="number" min={5} max={480} value={maxDurationMinutes}
          onChange={event => setMaxDurationMinutes(Math.min(480, Math.max(5, Number(event.target.value) || 5)))} />
      </label>
    </div>
    <div className="text-xs text-muted-foreground">授权范围：隔离工作区写入 + 已检测验证命令；联网、安装依赖和破坏性操作未授权。</div>
    <Button className="w-full" disabled={busy || !goal.trim() || workspace?.repoClean === false} onClick={() => void start()}>
      {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}启动研发
    </Button>

    {runs.length > 0 && <select className="h-9 w-full rounded border bg-background px-2 text-sm"
      value={activeId || ''} onChange={event => { setActiveId(event.target.value); setDetail(null); setDiff(null) }}>
      {runs.map(run => <option key={run.id} value={run.id}>{run.requirement.slice(0, 35)} · {PHASE_LABELS[run.phase || ''] || run.status}</option>)}
    </select>}

    {active && <div className="space-y-2 rounded border p-2 text-xs">
      <div className="flex items-center justify-between"><Badge>{PHASE_LABELS[active.phase || ''] || active.status}</Badge>
        <span>第 {active.iteration || 0}/{active.maxIterations || 12} 轮 · {elapsed} 分钟</span></div>
      <div className="grid grid-cols-4 gap-1">
        {['analyzing', 'implementing', 'testing', 'reviewing'].map(phase => <div key={phase}
          className={`rounded px-1 py-2 text-center ${active.phase === phase ? 'bg-primary text-primary-foreground' : 'bg-muted'}`}>{PHASE_LABELS[phase]}</div>)}
      </div>
      {(detail?.steps || []).slice(-6).map((step: any) => <div key={step.id} className="flex justify-between border-t pt-1">
        <span>第 {step.iteration} 轮 · {PHASE_LABELS[step.phase] || step.phase}</span><span>{step.status}</span>
      </div>)}
      {commandArtifacts.slice(-2).map((artifact: any) => <pre key={artifact.id} className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-slate-950 p-2 text-[10px] text-slate-100">{artifact.content}</pre>)}
      {active.errorMessage && <div className="flex gap-1 text-red-600"><AlertTriangle className="h-3 w-3 shrink-0" />{active.errorMessage}</div>}
      {(active.status === 'pending' || active.status === 'running') && <Button size="sm" variant="destructive" onClick={async () => {
        await cancelDevelopmentRun(active.id); await refreshRuns(); window.dispatchEvent(new CustomEvent('development-run-changed'))
      }}><Square className="mr-1 h-3 w-3" />取消</Button>}
      {active.phase === 'budget_exhausted' && <Button size="sm" onClick={async () => {
        await continueDevelopmentRun(active.id); setDetail(null); window.dispatchEvent(new CustomEvent('development-run-changed'))
      }}><RefreshCw className="mr-1 h-3 w-3" />追加 4 轮 / 30 分钟</Button>}
    </div>}

    {diff && <div className="space-y-2 rounded border p-2 text-xs">
      <div className="font-medium flex items-center gap-1"><GitCompare className="h-3 w-3" />待应用差异（{diff.files?.length || 0} 个文件）</div>
      <div className="max-h-20 overflow-auto">{diff.files?.map((file: string) => <div key={file}>{file}</div>)}</div>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-muted p-2 text-[10px]">{diff.patch || '无文本差异'}</pre>
      {active?.phase === 'awaiting_apply' && <Button size="sm" onClick={async () => {
        setBusy(true)
        try {
          await applyDevelopmentRun(active.id, diff.baseRevision, diff.diffDigest)
          setDetail(await fetchDevelopmentRun(active.id)); window.dispatchEvent(new CustomEvent('development-run-changed')); toast({ title: '已应用到项目', variant: 'success' })
        } catch (error) { toast({ title: '应用失败', description: String(error), variant: 'error' }) }
        finally { setBusy(false) }
      }}><CheckCircle2 className="mr-1 h-3 w-3" />审阅无误，应用到项目</Button>}
    </div>}
  </div>
}
