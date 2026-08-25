import { useState, useEffect, useCallback, useMemo } from 'react'
import { Header } from '@/components/layout/header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { toast } from '@/components/ui/toast'
import {
  FlaskConical,
  RefreshCw,
  Search,
  ExternalLink,
  CheckCircle2,
  XCircle,
  Clock,
  Play,
  TrendingUp,
  ChevronDown,
  ChevronRight,
  Settings
} from 'lucide-react'

// SwanLab 实验数据类型
interface SwanLabExperiment {
  cuid: string
  name: string
  description: string
  state: 'RUNNING' | 'FINISHED' | 'FAILED' | 'CRASHED' | 'PENDING'
  show: boolean
  createdAt: string
  finishedAt: string | null
  user: {
    username: string
    name: string
  }
  profile?: {
    config?: Record<string, any>
  }
  project: string
  workspace: {
    name: string
    username: string
  }
  summary?: Record<string, {
    step: number
    value: number
    min: { step: number; value: number }
    max: { step: number; value: number }
  }>
}

interface SwanLabProject {
  cuid: string
  name: string
  description: string
  visibility: string
  count: {
    experiments: number
    contributors: number
    runningExps: number
  }
}

const STATE_CONFIG: Record<string, { label: string; color: string; icon: typeof Clock }> = {
  RUNNING: { label: '运行中', color: 'bg-blue-500', icon: Play },
  FINISHED: { label: '已完成', color: 'bg-green-500', icon: CheckCircle2 },
  FAILED: { label: '失败', color: 'bg-red-500', icon: XCircle },
  CRASHED: { label: '崩溃', color: 'bg-orange-500', icon: XCircle },
  PENDING: { label: '等待中', color: 'bg-yellow-500', icon: Clock }
}

export default function ExperimentHub({ embedded = false }: { embedded?: boolean } = {}) {
  // 状态
  const [experiments, setExperiments] = useState<SwanLabExperiment[]>([])
  const [projects, setProjects] = useState<SwanLabProject[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isFetching, setIsFetching] = useState(false)
  const [lastFetchTime, setLastFetchTime] = useState<string | null>(null)
  const [selectedExperiment, setSelectedExperiment] = useState<SwanLabExperiment | null>(null)
  const [selectedProject, setSelectedProject] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedMetrics, setExpandedMetrics] = useState<Set<string>>(new Set())
  
  // SwanLab 连接状态
  const [swanlabStatus, setSwanlabStatus] = useState<{
    configured: boolean
    enabled: boolean
    connection: string
    workspaces: number
  } | null>(null)

  // 加载缓存数据
  const loadCachedData = useCallback(async () => {
    setIsLoading(true)
    try {
      const response = await fetch('/api/swanlab/cache')
      if (response.ok) {
        const data = await response.json()
        if (data.success && data.data) {
          setExperiments(data.data.experiments || [])
          setProjects(data.data.projects || [])
          if (data.data.timestamp) {
            setLastFetchTime(new Date(data.data.timestamp * 1000).toLocaleString('zh-CN'))
          }
        }
      }
    } catch (error) {
      console.error('Failed to load cached data:', error)
    } finally {
      setIsLoading(false)
    }
  }, [])

  // 检查 SwanLab 状态
  const checkStatus = useCallback(async () => {
    try {
      const response = await fetch('/api/swanlab/status')
      if (response.ok) {
        const data = await response.json()
        if (data.success) {
          setSwanlabStatus(data.status)
        }
      }
    } catch (error) {
      console.error('Failed to check status:', error)
    }
  }, [])

  // 从 SwanLab 拉取数据
  const fetchFromSwanLab = useCallback(async () => {
    if (!swanlabStatus?.configured) {
      toast({ 
        title: '未配置 SwanLab', 
        description: '请先前往设置页面配置 API Key',
        variant: 'error'
      })
      return
    }

    setIsFetching(true)
    try {
      const response = await fetch('/api/swanlab/fetch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      })

      if (response.ok) {
        const data = await response.json()
        if (data.success) {
          setExperiments(data.data.experiments || [])
          setProjects(data.data.projects || [])
          setLastFetchTime(new Date().toLocaleString('zh-CN'))
          toast({ 
            title: '数据获取成功', 
            description: `获取了 ${data.data.experiments?.length || 0} 个实验`,
            variant: 'success'
          })
        } else {
          toast({ 
            title: '获取失败', 
            description: data.error || '无法从 SwanLab 获取数据',
            variant: 'error'
          })
        }
      }
    } catch (error) {
      console.error('Fetch error:', error)
      toast({ title: '获取失败', description: '无法连接到服务器', variant: 'error' })
    } finally {
      setIsFetching(false)
    }
  }, [swanlabStatus])

  useEffect(() => {
    checkStatus()
    loadCachedData()
  }, [checkStatus, loadCachedData])

  // 筛选实验
  const filteredExperiments = useMemo(() => {
    return experiments.filter(exp => {
      if (selectedProject !== 'all' && exp.project !== selectedProject) return false
      if (searchQuery && !exp.name.toLowerCase().includes(searchQuery.toLowerCase())) return false
      return true
    })
  }, [experiments, selectedProject, searchQuery])

  // 统计数据
  const stats = useMemo(() => ({
    total: experiments.length,
    running: experiments.filter(e => e.state === 'RUNNING').length,
    finished: experiments.filter(e => e.state === 'FINISHED').length,
    failed: experiments.filter(e => e.state === 'FAILED' || e.state === 'CRASHED').length,
    projects: projects.length
  }), [experiments, projects])

  // 切换指标展开
  const toggleMetric = (metricName: string) => {
    const newExpanded = new Set(expandedMetrics)
    if (newExpanded.has(metricName)) {
      newExpanded.delete(metricName)
    } else {
      newExpanded.add(metricName)
    }
    setExpandedMetrics(newExpanded)
  }

  // 渲染指标卡片
  const renderMetricCard = (name: string, data: any) => {
    if (!data) return null
    const isExpanded = expandedMetrics.has(name)
    
    return (
      <div key={name} className="border rounded-lg p-3 bg-muted/30">
        <div 
          className="flex items-center justify-between cursor-pointer"
          onClick={() => toggleMetric(name)}
        >
          <div>
            <p className="font-medium text-sm">{name}</p>
            <p className="text-lg font-bold">{data.value?.toFixed(4) || 'N/A'}</p>
          </div>
          <Button variant="ghost" size="sm">
            {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </Button>
        </div>
        
        {isExpanded && (
          <div className="mt-3 pt-3 border-t text-sm space-y-1">
            <div className="flex justify-between">
              <span className="text-muted-foreground">最后 step:</span>
              <span>{data.step}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">最小值:</span>
              <span>{data.min?.value?.toFixed(4)} @ step {data.min?.step}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">最大值:</span>
              <span>{data.max?.value?.toFixed(4)} @ step {data.max?.step}</span>
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={embedded ? 'h-full flex flex-col overflow-hidden' : 'flex flex-col h-screen'}>
      {!embedded && (
      <Header
        title="实验管理"
        description="查看和分析 SwanLab 实验数据"
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={fetchFromSwanLab}
              disabled={isFetching || !swanlabStatus?.configured}
            >
              {isFetching ? (
                <>
                  <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  获取中...
                </>
              ) : (
                <>
                  <RefreshCw className="w-4 h-4 mr-2" />
                  从 SwanLab 获取
                </>
              )}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.location.href = '/settings'}
            >
              <Settings className="w-4 h-4 mr-2" />
              配置
            </Button>
          </div>
        }
      />
      )}

      {/* API Key 未配置提示 */}
      {swanlabStatus && !swanlabStatus.configured && (
        <div className="mx-4 mt-4 p-4 bg-amber-500/10 border border-amber-500/20 rounded-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-amber-500/20 flex items-center justify-center">
                <svg className="w-4 h-4 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <div>
                <p className="font-medium text-amber-900 dark:text-amber-200">未配置 SwanLab API Key</p>
                <p className="text-sm text-amber-700 dark:text-amber-300">实验管理功能需要配置 API Key 才能从 SwanLab 获取数据</p>
              </div>
            </div>
            <Button 
              variant="outline" 
              size="sm"
              className="border-amber-500/30 hover:bg-amber-500/10"
              onClick={() => window.location.href = '/settings'}
            >
              去设置
            </Button>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-hidden flex">
        {/* 左侧实验列表 */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* 统计卡片 */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 p-4 border-b">
            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">总实验</p>
                    <p className="text-2xl font-bold">{stats.total}</p>
                  </div>
                  <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center">
                    <FlaskConical className="w-4 h-4 text-blue-500" />
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">运行中</p>
                    <p className="text-2xl font-bold">{stats.running}</p>
                  </div>
                  <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center">
                    <Play className="w-4 h-4 text-blue-500" />
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">已完成</p>
                    <p className="text-2xl font-bold">{stats.finished}</p>
                  </div>
                  <div className="w-8 h-8 rounded-lg bg-green-500/10 flex items-center justify-center">
                    <CheckCircle2 className="w-4 h-4 text-green-500" />
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">失败</p>
                    <p className="text-2xl font-bold">{stats.failed}</p>
                  </div>
                  <div className="w-8 h-8 rounded-lg bg-red-500/10 flex items-center justify-center">
                    <XCircle className="w-4 h-4 text-red-500" />
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">项目</p>
                    <p className="text-2xl font-bold">{stats.projects}</p>
                  </div>
                  <div className="w-8 h-8 rounded-lg bg-purple-500/10 flex items-center justify-center">
                    <TrendingUp className="w-4 h-4 text-purple-500" />
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* 筛选栏 */}
          <div className="p-4 border-b space-y-3">
            <div className="flex gap-3">
              <div className="relative flex-1 max-w-sm">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="搜索实验..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9"
                />
              </div>
              <select
                className="px-3 py-2 rounded-md border border-input bg-background text-sm"
                value={selectedProject}
                onChange={(e) => setSelectedProject(e.target.value)}
              >
                <option value="all">所有项目</option>
                {projects.map(p => (
                  <option key={p.cuid} value={p.name}>{p.name}</option>
                ))}
              </select>
            </div>
            
            {lastFetchTime && (
              <p className="text-xs text-muted-foreground">
                上次更新: {lastFetchTime}
              </p>
            )}
            
          </div>

          {/* 实验列表 */}
          <ScrollArea className="flex-1 p-4">
            {isLoading ? (
              <div className="flex items-center justify-center py-12">
                <RefreshCw className="w-6 h-6 animate-spin text-muted-foreground" />
              </div>
            ) : filteredExperiments.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                <FlaskConical className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>暂无实验数据</p>
                <p className="text-sm">点击上方按钮从 SwanLab 获取</p>
              </div>
            ) : (
              <div className="space-y-2">
                {filteredExperiments.map((exp) => {
                  const statusConfig = STATE_CONFIG[exp.state] || STATE_CONFIG.PENDING
                  const StatusIcon = statusConfig.icon
                  
                  return (
                    <div
                      key={exp.cuid}
                      className={`p-4 border rounded-lg cursor-pointer transition-colors ${
                        selectedExperiment?.cuid === exp.cuid 
                          ? 'bg-primary/5 border-primary' 
                          : 'hover:bg-muted/50'
                      }`}
                      onClick={() => setSelectedExperiment(exp)}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <h3 className="font-medium truncate">{exp.name}</h3>
                            <Badge className={statusConfig.color}>
                              <StatusIcon className="w-3 h-3 mr-1" />
                              {statusConfig.label}
                            </Badge>
                          </div>
                          <p className="text-sm text-muted-foreground truncate">
                            {exp.description || '暂无描述'}
                          </p>
                          <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                            <span>{exp.project}</span>
                            <span>•</span>
                            <span>{exp.workspace?.name}</span>
                            <span>•</span>
                            <span>{new Date(exp.createdAt).toLocaleDateString('zh-CN')}</span>
                          </div>
                        </div>
                        
                        {exp.summary && Object.keys(exp.summary).length > 0 && (
                          <div className="ml-4 text-right">
                            <p className="text-xs text-muted-foreground">指标</p>
                            <p className="font-medium">{Object.keys(exp.summary).length}</p>
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </ScrollArea>
        </div>

        {/* 右侧详情面板 */}
        {selectedExperiment && (
          <div className="w-96 border-l bg-card overflow-y-auto">
            <div className="p-4 border-b sticky top-0 bg-card z-10">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold truncate flex-1">{selectedExperiment.name}</h3>
                <Button 
                  variant="ghost" 
                  size="sm" 
                  onClick={() => setSelectedExperiment(null)}
                >
                  ✕
                </Button>
              </div>
              
              {(() => {
                const statusConfig = STATE_CONFIG[selectedExperiment.state] || STATE_CONFIG.PENDING
                return (
                  <Badge className={`mt-2 ${statusConfig.color}`}>
                    {statusConfig.label}
                  </Badge>
                )
              })()}
            </div>

            <div className="p-4 space-y-6">
              {/* 基本信息 */}
              <div>
                <h4 className="text-sm font-medium mb-2">基本信息</h4>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">项目</span>
                    <span>{selectedExperiment.project}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">工作空间</span>
                    <span>{selectedExperiment.workspace?.name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">创建时间</span>
                    <span>{new Date(selectedExperiment.createdAt).toLocaleString('zh-CN')}</span>
                  </div>
                  {selectedExperiment.finishedAt && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">完成时间</span>
                      <span>{new Date(selectedExperiment.finishedAt).toLocaleString('zh-CN')}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* 配置参数 */}
              {selectedExperiment.profile?.config && Object.keys(selectedExperiment.profile.config).length > 0 && (
                <div>
                  <h4 className="text-sm font-medium mb-2">配置参数</h4>
                  <div className="bg-muted rounded-lg p-3">
                    <pre className="text-xs overflow-auto">
                      {JSON.stringify(selectedExperiment.profile.config, null, 2)}
                    </pre>
                  </div>
                </div>
              )}

              {/* 指标摘要 */}
              {selectedExperiment.summary && Object.keys(selectedExperiment.summary).length > 0 && (
                <div>
                  <h4 className="text-sm font-medium mb-2">指标摘要</h4>
                  <div className="space-y-2">
                    {Object.entries(selectedExperiment.summary).map(([name, data]) => 
                      renderMetricCard(name, data)
                    )}
                  </div>
                </div>
              )}

              {/* SwanLab 链接 */}
              <div>
                <a
                  href={`https://swanlab.cn/${selectedExperiment.workspace?.username}/${selectedExperiment.project}/runs/${selectedExperiment.cuid}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-center gap-2 w-full p-2 border rounded-lg hover:bg-muted transition-colors text-sm"
                >
                  <ExternalLink className="w-4 h-4" />
                  在 SwanLab 中查看
                </a>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
