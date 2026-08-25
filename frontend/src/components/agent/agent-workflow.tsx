import { useState, useEffect, useRef, useCallback } from 'react'
import { useLocation } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/utils'
import { useGenerationStore } from '@/stores/generationStore'
import {
  Bot,
  User,
  Layout,
  CheckCircle2,
  Loader2,
  Play,
  XCircle,
  ChevronRight,
  FileCode,
  ListTodo,
  Sparkles,
  ShieldAlert,
  Check,
  X
} from 'lucide-react'

// Agent 消息类型
interface AgentMessage {
  id: string
  agentRole: 'architect' | 'planner' | 'developer' | 'reviewer' | 'user'
  messageType: 'thinking' | 'action' | 'output' | 'error' | 'progress'
  content: string
  stepName?: string
  metadata?: Record<string, any>
  timestamp: number
}

// 工具审批信息（来自 SSE tool_approval 事件）
interface ApprovalInfo {
  approvalId: string
  tool: string
  parameters: Record<string, any>
  policy?: string
  status: 'pending' | 'approved' | 'denied' | 'timed_out' | 'cancelled'
}

// Session 类型（后台运行）
interface AgentRun {
  id: string
  projectId?: string
  requirement: string
  roles: string[]
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  errorMessage?: string
  resultSummary?: Record<string, any>
  createdAt: number
  startedAt?: number
  completedAt?: number
}

interface AgentWorkflowProps {
  projectId?: string
  requirement: string
  onComplete?: (result: Record<string, any>) => void
}

// Agent 角色配置
const agentConfig = {
  architect: {
    name: '架构师',
    description: '负责技术方案设计',
    icon: Layout,
    color: 'text-purple-500',
    bgColor: 'bg-purple-500/10',
    borderColor: 'border-purple-500/20'
  },
  planner: {
    name: '规划师',
    description: '负责任务分解规划',
    icon: ListTodo,
    color: 'text-blue-500',
    bgColor: 'bg-blue-500/10',
    borderColor: 'border-blue-500/20'
  },
  developer: {
    name: '开发工程师',
    description: '负责代码实现',
    icon: FileCode,
    color: 'text-green-500',
    bgColor: 'bg-green-500/10',
    borderColor: 'border-green-500/20'
  },
  reviewer: {
    name: '代码审查员',
    description: '负责代码审查',
    icon: CheckCircle2,
    color: 'text-orange-500',
    bgColor: 'bg-orange-500/10',
    borderColor: 'border-orange-500/20'
  },
  user: {
    name: '用户',
    description: '需求提出者',
    icon: User,
    color: 'text-gray-500',
    bgColor: 'bg-gray-500/10',
    borderColor: 'border-gray-500/20'
  }
}

export function AgentWorkflow({ projectId, requirement, onComplete }: AgentWorkflowProps) {
  const [isRunning, setIsRunning] = useState(false)
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [run, setRun] = useState<AgentRun | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [currentPhase, setCurrentPhase] = useState<'idle' | 'architect' | 'planner' | 'developer' | 'reviewer' | 'completed' | 'cancelled'>('idle')
  const [results, setResults] = useState<Record<string, any>>({})
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalInfo[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)
  const resultsRef = useRef<Record<string, any>>({})
  const cancelledRef = useRef(false)
  const location = useLocation()
  const { registerGeneration, markNotified } = useGenerationStore()

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  // 运行 Agent 工作流（后台非阻塞：提交即返回 runId，再订阅 SSE 实时事件）
  const runWorkflow = useCallback(async () => {
    if (!requirement.trim() || isRunning) return

    setIsRunning(true)
    setMessages([])
    setRun(null)
    setRunId(null)
    setResults({})
    setPendingApprovals([])
    resultsRef.current = {}
    cancelledRef.current = false
    setCurrentPhase('architect')

    // 1) 提交后台运行（请求立即返回，不阻塞）
    const submitRes = await fetch('/api/agent/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ requirement, projectId })
    })
    const submitData = await submitRes.json()
    if (!submitRes.ok || !submitData.success) {
      addMessage({
        agentRole: 'user',
        messageType: 'error',
        content: submitData.message || '提交运行失败',
        stepName: '错误'
      })
      setIsRunning(false)
      return
    }

    const rid = submitData.runId as string
    setRunId(rid)
    // 登记到全局 watcher：切走页面后，watcher 会在完成时弹提醒
    registerGeneration({ id: rid, type: 'agent', sourcePath: location.pathname, label: requirement })

    // 2) 订阅后台运行的 SSE 事件流（后台线程逐帧落库，此处轮询式消费）
    const response = await fetch(`/api/agent/runs/${rid}/stream`)
    if (!response.ok) {
      setIsRunning(false)
      return
    }

    const reader = response.body?.getReader()
    if (!reader) {
      setIsRunning(false)
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed || !trimmed.startsWith('data: ')) continue

        const data = trimmed.slice(6)
        if (data === '[DONE]') {
          setIsRunning(false)
          setCurrentPhase(cancelledRef.current ? 'cancelled' : 'completed')
          if (!cancelledRef.current) onComplete?.({ ...resultsRef.current })
          return
        }

        try {
          const parsed = JSON.parse(data)
          handleAgentUpdate(parsed)
        } catch {
          // 忽略解析错误
        }
      }
    }

    setIsRunning(false)
  }, [requirement, isRunning, projectId, onComplete])

  // 取消后台运行
  const cancelRun = useCallback(async () => {
    if (!runId) return
    try {
      await fetch(`/api/agent/runs/${runId}/cancel`, { method: 'POST' })
    } catch {
      // 忽略网络错误；最终状态由 SSE 的 run_cancelled 事件驱动
    }
  }, [runId])

  // 工具审批决策：批准 / 拒绝（runner 正轮询审批行，决策后自动恢复运行）
  const decideApproval = useCallback(async (approvalId: string, approved: boolean) => {
    if (!runId) return
    try {
      await fetch(`/api/agent/runs/${runId}/approvals/${approvalId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved })
      })
    } catch {
      // 网络异常时保持 pending，SSE 事件流兜底展示最终状态
    }
  }, [runId])

  // 处理 Agent 更新
  const handleAgentUpdate = (update: any) => {
    switch (update.type) {
      case 'phase_start':
        setCurrentPhase(update.phase)
        addMessage({
          agentRole: update.phase,
          messageType: 'action',
          content: update.message || `开始${agentConfig[update.phase as keyof typeof agentConfig]?.name || update.phase}`,
          stepName: '开始'
        })
        break

      case 'tool_approval': {
        // 工具审批事件：pending 入队列等待决策；终态移出并留痕
        const info: ApprovalInfo = {
          approvalId: update.approvalId,
          tool: update.tool,
          parameters: update.parameters || {},
          policy: update.policy,
          status: update.status
        }
        if (info.status === 'pending') {
          setPendingApprovals(prev =>
            prev.some(p => p.approvalId === info.approvalId) ? prev : [...prev, info]
          )
        } else {
          setPendingApprovals(prev => prev.filter(p => p.approvalId !== info.approvalId))
          const statusLabel: Record<string, string> = {
            approved: '已批准',
            denied: '已拒绝',
            timed_out: '审批超时（已拒绝）',
            cancelled: '已取消'
          }
          addMessage({
            agentRole: 'user',
            messageType: info.status === 'approved' ? 'action' : 'error',
            content: update.message || `工具 ${info.tool} ${statusLabel[info.status] || info.status}`,
            stepName: '审批'
          })
        }
        break
      }

      case 'start':
        addMessage({
          agentRole: update.agent,
          messageType: 'thinking',
          content: update.message,
          stepName: '初始化'
        })
        break

      case 'progress':
        addMessage({
          agentRole: update.agent,
          messageType: 'progress',
          content: update.step,
          stepName: update.step,
          metadata: { progress: update.progress }
        })
        if (run) {
          setRun({ ...run, status: 'running' })
        }
        break

      case 'complete': {
        const agent = update.agent
        if (agent) {
          resultsRef.current[agent] = update.result
          setResults(prev => ({ ...prev, [agent]: update.result }))
        }
        addMessage({
          agentRole: agent,
          messageType: 'output',
          content: '阶段产出完成',
          stepName: '完成',
          metadata: update.result
        })
        break
      }

      case 'run_complete':
        setCurrentPhase('completed')
        if (runId) markNotified(runId)
        break

      case 'run_cancelled':
        cancelledRef.current = true
        if (runId) markNotified(runId)
        addMessage({
          agentRole: 'user',
          messageType: 'error',
          content: update.message || '运行已取消',
          stepName: '取消'
        })
        break

      case 'error':
        if (runId) markNotified(runId)
        addMessage({
          agentRole: 'user',
          messageType: 'error',
          content: update.message,
          stepName: '错误'
        })
        break
    }
  }

  // 添加消息
  const addMessage = (message: Omit<AgentMessage, 'id' | 'timestamp'>) => {
    const newMessage: AgentMessage = {
      ...message,
      id: Date.now().toString() + Math.random().toString(36).slice(2, 6),
      timestamp: Date.now()
    }
    setMessages(prev => [...prev, newMessage])
  }

  // 渲染消息
  const renderMessage = (message: AgentMessage, index: number) => {
    const config = agentConfig[message.agentRole] || agentConfig.user
    const Icon = config.icon

    return (
      <div
        key={message.id || index}
        className={cn(
          'flex gap-3 p-3 rounded-lg mb-2',
          config.bgColor,
          'border',
          config.borderColor
        )}
      >
        <div className={cn('w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0', 'bg-white/50')}>
          <Icon className={cn('w-4 h-4', config.color)} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={cn('font-medium text-sm', config.color)}>{config.name}</span>
            {message.stepName && (
              <Badge variant="outline" className="text-xs">
                {message.stepName}
              </Badge>
            )}
          </div>
          <p className="text-sm text-foreground">{message.content}</p>

          {/* 显示进度 */}
          {message.metadata?.progress && (
            <div className="mt-2">
              <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                <div
                  className={cn('h-full transition-all duration-300', config.color.replace('text-', 'bg-'))}
                  style={{ width: `${message.metadata.progress}%` }}
                />
              </div>
              <span className="text-xs text-muted-foreground mt-1">{message.metadata.progress}%</span>
            </div>
          )}
        </div>
      </div>
    )
  }

  // 渲染各角色产物（通用化）
  const renderResults = () => {
    const entries = Object.entries(results)
    if (entries.length === 0) return null
    return (
      <div className="mt-4 pt-4 border-t space-y-3">
        {entries.map(([agent, res]) => {
          const cfg = agentConfig[agent as keyof typeof agentConfig]
          const structured = res?.structured || {}
          return (
            <div key={agent}>
              <p className="text-sm font-medium mb-2">{cfg?.name || agent} 产物</p>
              {structured.tech_stack?.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {structured.tech_stack.map((tech: string) => (
                    <Badge key={tech} variant="secondary">{tech}</Badge>
                  ))}
                </div>
              )}
              {structured.phases?.length > 0 && (
                <div className="space-y-2 mt-2">
                  {structured.phases.map((phase: any, idx: number) => (
                    <div key={idx} className="flex items-center gap-2 text-sm">
                      <ChevronRight className="w-4 h-4 text-muted-foreground" />
                      <span>{phase.name}</span>
                      <span className="text-muted-foreground">({phase.tasks?.length || 0} 个任务)</span>
                    </div>
                  ))}
                </div>
              )}
              {!structured.tech_stack?.length && !structured.phases?.length && (
                <p className="text-sm text-muted-foreground">
                  已完成（{(res?.raw_output || '').slice(0, 60)}…）
                </p>
              )}
            </div>
          )
        })}
      </div>
    )
  }

  const phaseText: Record<string, string> = {
    idle: '准备就绪',
    architect: '架构师正在设计方案...',
    planner: '规划师正在分解任务...',
    developer: '开发工程师正在实现...',
    reviewer: '评审专家正在审查...',
    completed: '规划完成！',
    cancelled: '运行已取消'
  }

  return (
    <Card className="w-full">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center">
              <Bot className="w-5 h-5 text-white" />
            </div>
            <div>
              <CardTitle className="text-lg">多 Agent 协作规划</CardTitle>
              <p className="text-sm text-muted-foreground">
                {phaseText[currentPhase]}
              </p>
            </div>
          </div>
          {isRunning ? (
            <Button
              onClick={cancelRun}
              variant="outline"
              className="gap-2"
            >
              <XCircle className="w-4 h-4" />
              取消
            </Button>
          ) : (
            <Button
              onClick={runWorkflow}
              disabled={!requirement.trim()}
              className="gap-2"
            >
              <Play className="w-4 h-4" />
              开始协作
            </Button>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {/* 消息列表 */}
        <ScrollArea ref={scrollRef} className="h-[400px] pr-4">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground">
              <Sparkles className="w-12 h-12 mb-4 opacity-50" />
              <p>点击"开始协作"启动多 Agent 规划</p>
              <p className="text-sm mt-2">后台运行 · Architect → Planner 协作流程</p>
            </div>
          ) : (
            <div className="space-y-2">
              {messages.map((msg, idx) => renderMessage(msg, idx))}

              {/* 待审批工具卡片 */}
              {pendingApprovals.map((ap) => (
                <div
                  key={ap.approvalId}
                  className="flex gap-3 p-3 rounded-lg mb-2 bg-amber-500/10 border border-amber-500/30"
                >
                  <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 bg-white/50">
                    <ShieldAlert className="w-4 h-4 text-amber-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium text-sm text-amber-600">工具审批</span>
                      <Badge variant="outline" className="text-xs">等待你的决策</Badge>
                      {ap.policy && (
                        <Badge variant="secondary" className="text-xs">{ap.policy}</Badge>
                      )}
                    </div>
                    <p className="text-sm text-foreground break-all">
                      Agent 请求调用工具 <code className="px-1 py-0.5 rounded bg-muted text-xs font-mono">{ap.tool}</code>
                    </p>
                    <pre className="mt-2 p-2 rounded-md bg-background/80 border border-border/50 text-xs font-mono text-muted-foreground overflow-x-auto max-h-40">
                      {JSON.stringify(ap.parameters, null, 2)}
                    </pre>
                    <div className="flex items-center gap-2 mt-2">
                      <Button
                        size="sm"
                        className="gap-1 bg-green-500 hover:bg-green-600 text-white"
                        onClick={() => decideApproval(ap.approvalId, true)}
                      >
                        <Check className="w-3.5 h-3.5" />
                        允许执行
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-1 text-red-600 border-red-300 hover:bg-red-50"
                        onClick={() => decideApproval(ap.approvalId, false)}
                      >
                        <X className="w-3.5 h-3.5" />
                        拒绝
                      </Button>
                    </div>
                  </div>
                </div>
              ))}

              {isRunning && (
                <div className="flex items-center gap-2 p-3 text-muted-foreground">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span className="text-sm">Agent 正在思考...</span>
                </div>
              )}
            </div>
          )}
        </ScrollArea>

        {/* 结果展示 */}
        {renderResults()}
      </CardContent>
    </Card>
  )
}
