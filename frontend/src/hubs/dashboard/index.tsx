import { useMemo, useState, useEffect, useCallback } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Header } from '@/components/layout/header'
import { CommandPalette } from '@/components/search/command-palette'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/utils'
import type { Task, SoftwareProject, Note, Experiment } from '@/types'
import {
  FileText,
  Code2,
  BookOpen,
  CheckSquare,
  ArrowRight,
  TrendingUp,
  Star,
  Eye,
  EyeOff,
  Tag,
  Folder,
  History,
  Loader2,
  AlertTriangle,
  Clock,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { formatDate, formatRelativeTime } from '@/utils'
import { usePapers } from '@/hooks/usePapers'

/** 交错进场延迟（尊重 prefers-reduced-motion，见 index.css） */
const fade = (i: number): CSSProperties => ({ animationDelay: `${i * 70}ms` })

/** 毛玻璃面板基元：用 .glass 取代默认实色卡片，承载 Depth 支柱 */
function Panel({
  className,
  style,
  children,
}: {
  className?: string
  style?: CSSProperties
  children: ReactNode
}) {
  return (
    <div className={cn('glass rounded-2xl', className)} style={style}>
      {children}
    </div>
  )
}

// 简单的进度条组件（单一强调色）
function ProgressBar({ value, max }: { value: number; max: number }) {
  const percentage = max > 0 ? (value / max) * 100 : 0
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-foreground/[0.06] dark:bg-white/[0.08]">
      <div
        className="h-full rounded-full bg-primary transition-all duration-500"
        style={{ width: `${percentage}%` }}
      />
    </div>
  )
}

// 后台 Agent 运行摘要（与运行历史页同源 /api/agent/runs）
interface AgentRunSummary {
  id: string
  requirement: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  createdAt: number
}

const RUN_STATUS_META: Record<AgentRunSummary['status'], { label: string; dot: string }> = {
  pending: { label: '排队中', dot: 'bg-gray-400' },
  running: { label: '进行中', dot: 'bg-blue-500' },
  completed: { label: '已完成', dot: 'bg-green-500' },
  failed: { label: '失败', dot: 'bg-red-500' },
  cancelled: { label: '已取消', dot: 'bg-amber-500' },
}

export default function Dashboard() {
  const { papers, ensureLoaded } = usePapers()

  const [tasks, setTasks] = useState<Task[]>([])
  const [projects, setProjects] = useState<SoftwareProject[]>([])
  const [notes, setNotes] = useState<Note[]>([])
  const [experiments, setExperiments] = useState<Experiment[]>([])
  const [agentRuns, setAgentRuns] = useState<AgentRunSummary[]>([])

  const loadData = useCallback(async () => {
    try {
      const [tasksRes, projectsRes, notesRes, swanlabCacheRes, agentRunsRes] = await Promise.all([
        fetch('/api/tasks'),
        fetch('/api/projects'),
        fetch('/api/notes'),
        fetch('/api/swanlab/cache'),
        fetch('/api/agent/runs?limit=5'),
      ])

      if (tasksRes.ok) {
        const data = await tasksRes.json()
        if (data.success) setTasks(data.tasks)
      }
      if (projectsRes.ok) {
        const data = await projectsRes.json()
        if (data.success) setProjects(data.projects)
      }
      if (notesRes.ok) {
        const data = await notesRes.json()
        if (data.success) setNotes(data.notes)
      }
      if (swanlabCacheRes.ok) {
        const data = await swanlabCacheRes.json()
        if (data.success && data.data) {
          setExperiments(data.data.experiments || [])
        }
      }
      if (agentRunsRes.ok) {
        const data = await agentRunsRes.json()
        if (data.success) setAgentRuns(data.runs || [])
      }
    } catch (error) {
      console.error('Failed to load dashboard data:', error)
    }
  }, [])

  useEffect(() => {
    loadData()
    void ensureLoaded()

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        loadData()
        void ensureLoaded()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [loadData, ensureLoaded])

  const paperStats = useMemo(() => {
    const total = papers.length
    const read = papers.filter((p) => p.isRead).length
    const unread = total - read
    const favorite = papers.filter((p) => p.isFavorite).length
    const withSummary = papers.filter((p) => p.summary).length

    const allTags = papers.flatMap((p) => p.tags || [])
    const tagCounts = allTags.reduce<Record<string, number>>((acc, tag) => {
      acc[tag] = (acc[tag] || 0) + 1
      return acc
    }, {})

    const topTags = Object.entries(tagCounts)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 10)

    const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000
    const recentPapers = papers.filter((p) => p.addedAt > sevenDaysAgo)

    return {
      total,
      read,
      unread,
      favorite,
      withSummary,
      readPercentage: total > 0 ? Math.round((read / total) * 100) : 0,
      topTags,
      recentPapers,
    }
  }, [papers])

  const openTasks = tasks.filter((t) => t.status !== 'done' && t.status !== 'archived').length
  const pendingTasks = tasks.filter((t) => t.status !== 'done' && t.status !== 'archived')
  const urgentTasks = tasks.filter((t) => t.priority === 'urgent' && t.status !== 'done').length
  const developingProjects = projects.filter((p) => p.status === 'developing').length
  const favoriteNotes = notes.filter((n) => n.isFavorite).length
  const runningExperiments = experiments.filter((e: any) => e.state === 'RUNNING').length

  // 统计指标：单一强调色，图标统一中性处理，层级靠字号而非色彩
  const stats = [
    { label: '论文总数', value: paperStats.total, delta: `+${paperStats.recentPapers.length} 本周新增`, icon: FileText },
    { label: '阅读进度', value: `${paperStats.readPercentage}%`, delta: `${paperStats.read} 已读 / ${paperStats.unread} 未读`, icon: Eye },
    { label: '收藏论文', value: paperStats.favorite, delta: `${paperStats.withSummary} 篇已总结`, icon: Star },
    { label: '待办任务', value: openTasks, delta: `${urgentTasks} 个紧急`, icon: CheckSquare },
    { label: '软件项目', value: projects.length, delta: `${developingProjects} 个开发中`, icon: Folder },
    { label: '知识笔记', value: notes.length, delta: `${favoriteNotes} 个收藏`, icon: BookOpen },
    { label: 'SwanLab 实验', value: experiments.length, delta: `${runningExperiments} 个运行中`, icon: TrendingUp },
  ]

  const quickActions = [
    { title: '抓取论文', description: '从 arXiv 获取最新 CV 论文', path: '/paper', icon: FileText },
    { title: '新建项目', description: '用 AI 辅助开发新软件', path: '/software', icon: Code2 },
    { title: '记录笔记', description: '保存研究灵感', path: '/knowledge', icon: BookOpen },
  ]

  return (
    <div className="flex flex-col h-screen">
      <Header
        title="仪表盘"
        actions={<CommandPalette isGlobal={false} />}
      />

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl p-6 space-y-8">
          {/* Hero —— 克制、留白、无渐变欢迎条 */}
          <div className="animate-fade-up">
            <p className="text-xs font-semibold tracking-[0.22em] text-primary uppercase">
              AI Research OS
            </p>
            <h2 className="font-display text-4xl sm:text-5xl font-semibold tracking-tight mt-2">
              研究控制台
            </h2>
            <p className="text-muted-foreground mt-2 max-w-xl">
              你的智能研究助手，让文献、实验与代码在同一处流动。
            </p>
          </div>

          {/* 统计卡片 —— 玻璃面板 + 大号展示字体数字 */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-4">
            {stats.map((s, i) => (
              <Panel key={s.label} className="p-5 animate-fade-up" style={fade(i)}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm text-muted-foreground truncate">{s.label}</p>
                    <p className="font-display text-4xl font-semibold tabular-nums leading-tight mt-2">
                      {s.value}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1 truncate">{s.delta}</p>
                  </div>
                  <div className="w-9 h-9 rounded-xl bg-foreground/[0.04] dark:bg-white/[0.06] flex items-center justify-center text-foreground/50 flex-shrink-0">
                    <s.icon className="w-[18px] h-[18px]" />
                  </div>
                </div>
              </Panel>
            ))}
          </div>

          {/* 两栏：左论文列表，右侧标签 + 快速操作 */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <Panel className="lg:col-span-2 p-6 animate-fade-up" style={fade(7)}>
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-display font-semibold text-lg">最近添加的论文</h3>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    最近收藏的 {Math.min(papers.length, 5)} 篇论文
                  </p>
                </div>
                <Link to="/paper">
                  <button className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
                    查看全部 <ArrowRight className="w-4 h-4" />
                  </button>
                </Link>
              </div>

              <div className="mt-4">
                {papers.length === 0 ? (
                  <div className="text-center py-12 text-muted-foreground">
                    <FileText className="w-12 h-12 mx-auto mb-4 opacity-40" />
                    <p>还没有收藏论文</p>
                    <Link to="/paper">
                      <button className="mt-4 rounded-lg border border-border px-4 py-2 text-sm hover:bg-foreground/[0.04] dark:hover:bg-white/[0.06] transition-colors">
                        去抓取论文
                      </button>
                    </Link>
                  </div>
                ) : (
                  <div className="space-y-1">
                    {papers.slice(0, 5).map((paper) => (
                      <Link to="/paper" key={paper.id}>
                        <div className="row-hover flex items-start gap-3 p-3 -mx-3">
                          <div
                            className={cn(
                              'w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0',
                              paper.isRead
                                ? 'bg-foreground/[0.04] dark:bg-white/[0.06]'
                                : 'bg-primary/10'
                            )}
                          >
                            {paper.isRead ? (
                              <Eye className="w-5 h-5 text-foreground/50" />
                            ) : (
                              <EyeOff className="w-5 h-5 text-primary" />
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="font-medium truncate">{paper.title}</p>
                            <p className="text-sm text-muted-foreground truncate">
                              {paper.authors.slice(0, 3).join(', ')}
                              {paper.authors.length > 3 && ' et al.'}
                            </p>
                            <div className="flex items-center gap-2 mt-2">
                              {paper.tags?.slice(0, 3).map((tag) => (
                                <span
                                  key={tag}
                                  className="rounded-md bg-foreground/[0.04] dark:bg-white/[0.06] px-2 py-0.5 text-xs text-muted-foreground"
                                >
                                  {tag}
                                </span>
                              ))}
                              {paper.isFavorite && (
                                <span className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-xs text-yellow-600 dark:text-yellow-500">
                                  <Star className="w-3 h-3" /> 收藏
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="text-right text-sm text-muted-foreground flex-shrink-0">
                            <p>{formatRelativeTime(paper.addedAt)}</p>
                            <p className="text-xs">{formatDate(paper.publishedDate)}</p>
                          </div>
                        </div>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            </Panel>

            <div className="space-y-6">
              {/* 今日待办：任务清单收敛为仪表盘聚合入口，/task 路由仍保留 */}
              <Panel className="p-6 animate-fade-up" style={fade(8)}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <CheckSquare className="w-5 h-5 text-primary" />
                    <h3 className="font-display font-semibold text-lg">今日待办</h3>
                  </div>
                  <Link to="/task" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
                    查看全部 <ArrowRight className="w-4 h-4" />
                  </Link>
                </div>
                <p className="text-sm text-muted-foreground mt-0.5 mb-4">
                  {pendingTasks.length > 0 ? `${pendingTasks.length} 项未完成 · ${urgentTasks} 项紧急` : '没有待办任务'}
                </p>
                {pendingTasks.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-4">暂无待办，享受研究吧</p>
                ) : (
                  <div className="space-y-1">
                    {pendingTasks.slice(0, 5).map((t) => (
                      <Link to="/task" key={t.id}>
                        <div className="row-hover flex items-center gap-3 p-2 -mx-2 rounded-lg">
                          <span
                            className={cn(
                              'w-2 h-2 rounded-full shrink-0',
                              t.priority === 'urgent'
                                ? 'bg-red-500'
                                : t.priority === 'high'
                                  ? 'bg-amber-500'
                                  : 'bg-foreground/20'
                            )}
                          />
                          <span className="flex-1 min-w-0 text-sm font-medium truncate">{t.title}</span>
                          {t.priority === 'urgent' && (
                            <Badge variant="secondary" className="text-xs">紧急</Badge>
                          )}
                        </div>
                      </Link>
                    ))}
                  </div>
                )}
              </Panel>

              {/* 后台任务：运行历史收敛为仪表盘聚合入口，/agent-runs 路由仍保留 */}
              <Panel className="p-6 animate-fade-up" style={fade(9)}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <History className="w-5 h-5 text-primary" />
                    <h3 className="font-display font-semibold text-lg">后台任务</h3>
                  </div>
                  <Link to="/agent-runs" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
                    全部 <ArrowRight className="w-4 h-4" />
                  </Link>
                </div>
                <p className="text-sm text-muted-foreground mt-0.5 mb-4">最近的多 Agent 运行</p>
                {agentRuns.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-4">暂无后台运行记录</p>
                ) : (
                  <div className="space-y-1">
                    {agentRuns.slice(0, 4).map((run) => {
                      const meta = RUN_STATUS_META[run.status] || RUN_STATUS_META.pending
                      const Icon = run.status === 'running'
                        ? Loader2
                        : run.status === 'failed'
                          ? AlertTriangle
                          : Clock
                      return (
                        <Link to="/agent-runs" key={run.id}>
                          <div className="row-hover flex items-center gap-3 p-2 -mx-2 rounded-lg">
                            <Icon
                              className={cn(
                                'w-4 h-4 shrink-0',
                                run.status === 'running' && 'animate-spin text-blue-500',
                                run.status === 'failed' && 'text-red-500',
                                (run.status === 'completed' || run.status === 'cancelled' || run.status === 'pending') && 'text-muted-foreground'
                              )}
                            />
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium truncate">{run.requirement}</p>
                              <p className="text-xs text-muted-foreground mt-0.5">
                                {meta.label} · {formatRelativeTime(run.createdAt)}
                              </p>
                            </div>
                            <span className={cn('w-2 h-2 rounded-full shrink-0', meta.dot)} />
                          </div>
                        </Link>
                      )
                    })}
                  </div>
                )}
              </Panel>

              <Panel className="p-6 animate-fade-up" style={fade(10)}>
                <div className="flex items-center gap-2">
                  <Tag className="w-5 h-5 text-primary" />
                  <h3 className="font-display font-semibold text-lg">热门标签</h3>
                </div>
                <p className="text-sm text-muted-foreground mt-0.5 mb-4">你最关注的方向</p>
                {paperStats.topTags.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-4">
                    还没有标签，去为论文添加标签吧
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {paperStats.topTags.map(([tag, count]) => (
                      <span
                        key={tag}
                        className="rounded-md bg-foreground/[0.04] dark:bg-white/[0.06] px-3 py-1 text-sm"
                      >
                        {tag} <span className="text-muted-foreground">({count})</span>
                      </span>
                    ))}
                  </div>
                )}
              </Panel>

              <Panel className="p-6 animate-fade-up" style={fade(11)}>
                <h3 className="font-display font-semibold text-lg">快速操作</h3>
                <p className="text-sm text-muted-foreground mt-0.5 mb-2">常用功能入口</p>
                <div className="divide-y divide-border/60 -mx-2">
                  {quickActions.map((action) => (
                    <Link to={action.path} key={action.title}>
                      <div className="row-hover flex items-center justify-between px-2 py-3 group">
                        <span className="flex items-center gap-3">
                          <div className="w-9 h-9 rounded-xl bg-foreground/[0.04] dark:bg-white/[0.06] flex items-center justify-center text-foreground/60">
                            <action.icon className="w-[18px] h-[18px]" />
                          </div>
                          <span className="font-medium">{action.title}</span>
                        </span>
                        <ArrowRight className="w-4 h-4 text-muted-foreground group-hover:translate-x-1 transition-transform" />
                      </div>
                    </Link>
                  ))}
                </div>
              </Panel>
            </div>
          </div>

          {/* 阅读统计 —— 单一强调色进度条 */}
          {papers.length > 0 && (
            <Panel className="p-6 animate-fade-up" style={fade(12)}>
              <div className="flex items-center gap-2 mb-1">
                <TrendingUp className="w-5 h-5 text-primary" />
                <h3 className="font-display font-semibold text-lg">阅读统计</h3>
              </div>
              <p className="text-sm text-muted-foreground mb-5">论文阅读情况概览</p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2 text-muted-foreground">
                      <Eye className="w-4 h-4" /> 已读论文
                    </span>
                    <span className="font-medium tabular-nums">{paperStats.read}</span>
                  </div>
                  <ProgressBar value={paperStats.read} max={paperStats.total} />
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2 text-muted-foreground">
                      <EyeOff className="w-4 h-4" /> 未读论文
                    </span>
                    <span className="font-medium tabular-nums">{paperStats.unread}</span>
                  </div>
                  <ProgressBar value={paperStats.unread} max={paperStats.total} />
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2 text-muted-foreground">
                      <Star className="w-4 h-4" /> 已收藏
                    </span>
                    <span className="font-medium tabular-nums">{paperStats.favorite}</span>
                  </div>
                  <ProgressBar value={paperStats.favorite} max={paperStats.total} />
                </div>
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  )
}
