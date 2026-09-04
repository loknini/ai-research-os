import { useState, useEffect, useCallback } from 'react'
import { Header, HeaderAction } from '@/components/layout/header'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { VersionHistory } from '@/components/ui/version-history'
import { toast } from '@/components/ui/toast'
import type { Task, TaskStatus, TaskPriority, SoftwareProject } from '@/types'
import { Plus, CheckCircle2, Circle, Clock, Search, Filter, Folder } from 'lucide-react'

import { PRIORITY_CONFIG } from './config'
import { buildTaskTree } from './utils/taskTree'
import {
  fetchTasks,
  fetchProjects,
  saveTask,
  deleteTaskApi,
  updateTaskStatus
} from './services/tasksApi'
import { useTaskData } from './hooks/useTaskData'
import TaskItem from './components/TaskItem'
import TaskForm from './components/TaskForm'

export default function TaskHub() {
  // 状态
  const [tasks, setTasks] = useState<Task[]>([])
  const [projects, setProjects] = useState<SoftwareProject[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [showAddForm, setShowAddForm] = useState(false)
  const [editingTask, setEditingTask] = useState<Task | null>(null)
  const [deletingTask, setDeletingTask] = useState<Task | null>(null)

  // 筛选状态
  const [filterStatus, setFilterStatus] = useState<TaskStatus | 'all'>('all')
  const [filterPriority, setFilterPriority] = useState<TaskPriority | 'all'>('all')
  const [filterProject, setFilterProject] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [showFilters, setShowFilters] = useState(false)

  // 表单状态
  const [formData, setFormData] = useState<Partial<Task>>({
    title: '',
    description: '',
    status: 'todo',
    priority: 'medium',
    tags: [],
    projectId: undefined
  })
  const [tagInput, setTagInput] = useState('')

  // 版本历史状态
  const [showVersionHistory, setShowVersionHistory] = useState(false)
  const [versionHistoryTaskId, setVersionHistoryTaskId] = useState<string | null>(null)

  // 加载任务和项目
  const loadData = useCallback(async () => {
    setIsLoading(true)
    try {
      const [tasksData, projectsData] = await Promise.all([
        fetchTasks(),
        fetchProjects()
      ])
      setTasks(buildTaskTree(tasksData))
      setProjects(projectsData)
    } catch (error) {
      console.error('Failed to load data:', error)
      toast({ title: '加载失败', description: '无法加载任务数据', variant: 'error' })
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  // 派生数据：统计 + 过滤后的任务树
  const { stats, filteredTasks } = useTaskData({
    tasks,
    filterStatus,
    filterPriority,
    filterProject,
    searchQuery
  })

  // 创建/更新任务
  const handleSaveTask = async () => {
    if (!formData.title?.trim()) {
      toast({ title: '请输入任务标题', variant: 'error' })
      return
    }

    try {
      const success = await saveTask(formData, editingTask)
      if (success) {
        toast({
          title: editingTask ? '任务已更新' : '任务已创建',
          variant: 'success'
        })
        setShowAddForm(false)
        setEditingTask(null)
        setFormData({ title: '', description: '', status: 'todo', priority: 'medium', tags: [] })
        loadData()
      }
    } catch (error) {
      console.error('Save task error:', error)
      toast({ title: '保存失败', variant: 'error' })
    }
  }

  // 删除任务
  const handleDeleteTask = async () => {
    if (!deletingTask) return

    try {
      const success = await deleteTaskApi(deletingTask.id)
      if (success) {
        toast({ title: '任务已删除', variant: 'success' })
        setDeletingTask(null)
        loadData()
      }
    } catch (error) {
      console.error('Delete task error:', error)
      toast({ title: '删除失败', variant: 'error' })
    }
  }

  // 更新任务状态
  const handleStatusChange = async (task: Task, newStatus: TaskStatus) => {
    try {
      const success = await updateTaskStatus(
        task.id,
        newStatus,
        newStatus === 'done' ? Date.now() : null
      )
      if (success) {
        loadData()
      }
    } catch (error) {
      console.error('Update status error:', error)
    }
  }

  // 添加标签
  const handleAddTag = () => {
    if (tagInput.trim() && !formData.tags?.includes(tagInput.trim())) {
      setFormData({ ...formData, tags: [...(formData.tags || []), tagInput.trim()] })
      setTagInput('')
    }
  }

  return (
    <div className="flex flex-col h-screen">
      <Header
        title="任务管理"
        actions={
          <HeaderAction
            icon={Plus}
            label="新建任务"
            onClick={() => {
              setEditingTask(null)
              setFormData({ title: '', description: '', status: 'todo', priority: 'medium', tags: [] })
              setShowAddForm(true)
            }}
          />
        }
      />

      <div className="flex-1 overflow-hidden flex">
        {/* 主内容区 */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* 统计卡片 */}
          <div className="grid grid-cols-4 gap-4 p-6 pb-0">
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">总任务</p>
                    <p className="text-2xl font-bold">{stats.total}</p>
                  </div>
                  <div className="p-3 bg-primary/10 rounded-full">
                    <Circle className="w-5 h-5 text-primary" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">待办</p>
                    <p className="text-2xl font-bold">{stats.todo}</p>
                  </div>
                  <div className="p-3 bg-slate-500/10 rounded-full">
                    <Clock className="w-5 h-5 text-slate-500" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">进行中</p>
                    <p className="text-2xl font-bold">{stats.inProgress}</p>
                  </div>
                  <div className="p-3 bg-blue-500/10 rounded-full">
                    <Clock className="w-5 h-5 text-blue-500" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">已完成</p>
                    <p className="text-2xl font-bold">{stats.done}</p>
                  </div>
                  <div className="p-3 bg-green-500/10 rounded-full">
                    <CheckCircle2 className="w-5 h-5 text-green-500" />
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* 搜索和筛选 */}
          <div className="px-6 py-4">
            <div className="flex items-center gap-4">
              <div className="relative flex-1 max-w-md">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="搜索任务..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9"
                />
              </div>
              <Button
                variant="outline"
                onClick={() => setShowFilters(!showFilters)}
                className={showFilters ? 'bg-muted' : ''}
              >
                <Filter className="w-4 h-4 mr-2" />
                筛选
              </Button>
            </div>

            {showFilters && (
              <div className="flex flex-wrap items-center gap-4 mt-4 p-4 bg-muted/50 rounded-lg">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">状态:</span>
                  <select
                    className="h-9 px-3 rounded-md border border-input bg-background text-sm"
                    value={filterStatus}
                    onChange={(e) => setFilterStatus(e.target.value as TaskStatus | 'all')}
                  >
                    <option value="all">全部</option>
                    <option value="todo">待办</option>
                    <option value="in_progress">进行中</option>
                    <option value="done">已完成</option>
                  </select>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">优先级:</span>
                  <select
                    className="h-9 px-3 rounded-md border border-input bg-background text-sm"
                    value={filterPriority}
                    onChange={(e) => setFilterPriority(e.target.value as TaskPriority | 'all')}
                  >
                    <option value="all">全部</option>
                    <option value="low">低</option>
                    <option value="medium">中</option>
                    <option value="high">高</option>
                    <option value="urgent">紧急</option>
                  </select>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">项目:</span>
                  <select
                    className="h-9 px-3 rounded-md border border-input bg-background text-sm"
                    value={filterProject}
                    onChange={(e) => setFilterProject(e.target.value)}
                  >
                    <option value="all">全部</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setFilterStatus('all')
                    setFilterPriority('all')
                    setFilterProject('all')
                    setSearchQuery('')
                  }}
                >
                  清除筛选
                </Button>
              </div>
            )}
          </div>

          {/* 任务列表 */}
          <ScrollArea className="flex-1 px-6 pb-6">
            <Card>
              <CardHeader>
                <CardTitle>任务列表</CardTitle>
                <CardDescription>
                  共 {filteredTasks.length} 个任务
                  {stats.overdue > 0 && (
                    <span className="ml-2 text-red-500">
                      (包含 {stats.overdue} 个逾期任务)
                    </span>
                  )}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {isLoading ? (
                  <div className="flex items-center justify-center py-12">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
                  </div>
                ) : filteredTasks.length === 0 ? (
                  <div className="text-center py-12 text-muted-foreground">
                    <CheckCircle2 className="w-12 h-12 mx-auto mb-4 opacity-50" />
                    <p>暂无任务</p>
                    <p className="text-sm mt-1">点击"新建任务"开始管理你的工作</p>
                  </div>
                ) : (
                  <div className="space-y-1">
                    {filteredTasks.map((task) => (
                      <TaskItem
                        key={task.id}
                        task={task}
                        depth={0}
                        projects={projects}
                        onStatusChange={handleStatusChange}
                        onEdit={(task) => {
                          setEditingTask(task)
                          setFormData(task)
                          setShowAddForm(true)
                        }}
                        onDelete={(task) => setDeletingTask(task)}
                        onShowHistory={(taskId) => {
                          setVersionHistoryTaskId(taskId)
                          setShowVersionHistory(true)
                        }}
                      />
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </ScrollArea>
        </div>

        {/* 侧边栏 - 优先级统计 */}
        <div className="w-64 border-l p-6 hidden xl:block">
          <h3 className="font-semibold mb-4">按优先级</h3>
          <div className="space-y-3">
            {Object.entries(PRIORITY_CONFIG).map(([priority, config]) => (
              <div key={priority} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className={`w-3 h-3 rounded-full ${config.color}`} />
                  <span className="text-sm">{config.label}</span>
                </div>
                <span className="text-sm font-medium">{stats.byPriority[priority as TaskPriority]}</span>
              </div>
            ))}
          </div>

          <Separator className="my-6" />

          <h3 className="font-semibold mb-4">项目</h3>
          <div className="space-y-2">
            {projects.map((project) => {
              const count = tasks.filter((t) => t.projectId === project.id).length
              return (
                <button
                  key={project.id}
                  onClick={() => setFilterProject(project.id)}
                  className={`w-full flex items-center justify-between p-2 rounded-lg text-sm transition-colors ${
                    filterProject === project.id ? 'bg-primary/10 text-primary' : 'hover:bg-muted'
                  }`}
                >
                  <span className="flex items-center gap-2 truncate">
                    <Folder className="w-4 h-4" />
                    {project.name}
                  </span>
                  <span className="text-muted-foreground">{count}</span>
                </button>
              )
            })}
          </div>
        </div>
      </div>

      {/* 添加/编辑任务对话框 */}
      <TaskForm
        isOpen={showAddForm}
        editingTask={editingTask}
        formData={formData}
        setFormData={setFormData}
        tagInput={tagInput}
        setTagInput={setTagInput}
        handleAddTag={handleAddTag}
        handleSaveTask={handleSaveTask}
        onCancel={() => setShowAddForm(false)}
        projects={projects}
      />

      {/* 删除确认对话框 */}
      <ConfirmDialog
        isOpen={!!deletingTask}
        onClose={() => setDeletingTask(null)}
        onConfirm={handleDeleteTask}
        title="删除任务"
        message={`确定要删除任务 "${deletingTask?.title}" 吗？此操作不可恢复。`}
        confirmText="删除"
        cancelText="取消"
        variant="danger"
      />

      {/* 版本历史对话框 */}
      <VersionHistory
        entityType="task"
        entityId={versionHistoryTaskId || ''}
        isOpen={showVersionHistory}
        onClose={() => {
          setShowVersionHistory(false)
          setVersionHistoryTaskId(null)
        }}
        onRestore={(_data) => {
          // 恢复后刷新数据
          loadData()
        }}
      />
    </div>
  )
}
