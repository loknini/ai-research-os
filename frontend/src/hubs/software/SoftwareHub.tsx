import { useState, useEffect, useCallback } from 'react'
import { Header, HeaderAction } from '@/components/layout/header'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { toast } from '@/components/ui/toast'
import type { SoftwareProject, ProjectStatus, Task } from '@/types'
import { Plus, Code2, Folder, FolderOpen, Lightbulb, Rocket, Search } from 'lucide-react'
import { STATUS_CONFIG } from './config'
import { Button } from '@/components/ui/button'
import {
  fetchProjects,
  fetchTasks,
  saveProject,
  updateProject,
  createDefaultTasks,
  deleteProjectApi
} from './services/projectsApi'
import { useSoftwareData } from './hooks/useSoftwareData'
import { ProjectCard } from './components/ProjectCard'
import { ProjectDetail } from './components/ProjectDetail'
import { ProjectForm } from './components/ProjectForm'
import { IdeaFormDialog } from './components/IdeaFormDialog'

export default function SoftwareHub({ embedded = false }: { embedded?: boolean } = {}) {
  // 状态
  const [projects, setProjects] = useState<SoftwareProject[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [showIdeaForm, setShowIdeaForm] = useState(false)
  const [selectedProject, setSelectedProject] = useState<SoftwareProject | null>(null)
  const [deletingProject, setDeletingProject] = useState<SoftwareProject | null>(null)
  const [editingProject, setEditingProject] = useState<SoftwareProject | null>(null)
  const [projectFormMode, setProjectFormMode] = useState<'create' | 'import'>('create')

  // 筛选
  const [filterStatus, setFilterStatus] = useState<ProjectStatus | 'all'>('all')
  const [searchQuery, setSearchQuery] = useState('')

  // Agent 协作状态（由 AgentWorkflow 组件管理）

  // 表单状态
  const [ideaDescription, setIdeaDescription] = useState('')
  const [formData, setFormData] = useState<Partial<SoftwareProject>>({
    name: '',
    description: '',
    techStack: [],
    status: 'design',
    localPath: ''
  })

  // 加载数据
  const loadData = useCallback(async () => {
    setIsLoading(true)
    try {
      const [projectsRes, tasksRes] = await Promise.all([
        fetchProjects(),
        fetchTasks()
      ])

      if (projectsRes.ok) {
        const data = await projectsRes.json()
        if (data.success) setProjects(data.projects)
      }
      if (tasksRes.ok) {
        const data = await tasksRes.json()
        if (data.success) setTasks(data.tasks)
      }
    } catch (error) {
      console.error('Failed to load data:', error)
      toast({ title: '加载失败', description: '无法加载项目数据', variant: 'error' })
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  // 统计数据 + 筛选项目
  const { stats, filteredProjects } = useSoftwareData(projects, filterStatus, searchQuery)

  // Agent 协作结果处理（已由 AgentWorkflow 组件处理）

  // 保存项目
  const handleSaveProject = async () => {
    if (!formData.name?.trim()) {
      toast({ title: '请输入项目名称', variant: 'error' })
      return
    }

    try {
      const response = editingProject
        ? await updateProject(editingProject.id, formData)
        : await saveProject(formData)

      if (response.ok) {
        const result = await response.json()

        if (result.success) {
          toast({
            title: editingProject ? '项目已更新' : '项目已创建',
            variant: 'success'
          })

          // 如果创建了新项目，自动创建相关任务（导入现有项目除外）
          if (!editingProject && result.project) {
            const projectId = result.project.id
            if (projectFormMode !== 'import') {
              await createDefaultTasks(projectId)
            }
          }

          setShowCreateForm(false)
          setEditingProject(null)
          setProjectFormMode('create')
          setFormData({ name: '', description: '', techStack: [], status: 'design' })
          loadData()
        }
      }
    } catch (error) {
      console.error('Save project error:', error)
      toast({ title: '保存失败', variant: 'error' })
    }
  }

  // 删除项目
  const handleDeleteProject = async () => {
    if (!deletingProject) return

    try {
      const response = await deleteProjectApi(deletingProject.id)
      if (response.ok) {
        toast({ title: '项目已删除', variant: 'success' })
        setDeletingProject(null)
        if (selectedProject?.id === deletingProject.id) {
          setSelectedProject(null)
        }
        loadData()
      }
    } catch (error) {
      console.error('Delete project error:', error)
      toast({ title: '删除失败', variant: 'error' })
    }
  }

  // 打开新建/导入项目表单
  const openProjectForm = (mode: 'create' | 'import') => {
    setEditingProject(null)
    setProjectFormMode(mode)
    setFormData({ name: '', description: '', techStack: [], status: 'design', localPath: '' })
    setShowCreateForm(true)
  }

  return (
    <div className={embedded ? 'h-full flex flex-col overflow-hidden' : 'flex flex-col h-screen'}>
      {!embedded && (
      <Header
        title="软件开发"
        description="AI 辅助软件开发，从想法到部署"
        actions={
          <>
            <HeaderAction
              icon={Lightbulb}
              label="从想法开始"
              onClick={() => setShowIdeaForm(true)}
            />
            <HeaderAction
              icon={Plus}
              label="新建项目"
              onClick={() => {
                setEditingProject(null)
                setFormData({ name: '', description: '', techStack: [], status: 'design' })
                setShowCreateForm(true)
              }}
            />
          </>
        }
      />
      )}

      <div className="flex-1 overflow-hidden flex">
        {/* 项目列表 */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* embedded 模式下 SoftwareHub 自己的 Header 被隐藏，需要在这里补充操作入口 */}
          {embedded && (
            <div className="flex items-center justify-end gap-2 mb-4">
              <Button variant="outline" size="sm" onClick={() => setShowIdeaForm(true)}>
                <Lightbulb className="w-4 h-4 mr-2" /> 从想法开始
              </Button>
              <Button variant="outline" size="sm" onClick={() => openProjectForm('import')}>
                <FolderOpen className="w-4 h-4 mr-2" /> 导入现有项目
              </Button>
              <Button size="sm" onClick={() => openProjectForm('create')}>
                <Plus className="w-4 h-4 mr-2" /> 新建项目
              </Button>
            </div>
          )}

          {/* 统计 */}
          <div className="grid grid-cols-4 gap-4 mb-6">
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">总项目</p>
                    <p className="text-2xl font-bold">{stats.total}</p>
                  </div>
                  <div className="p-3 bg-primary/10 rounded-full">
                    <Folder className="w-5 h-5 text-primary" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">设计阶段</p>
                    <p className="text-2xl font-bold">{stats.byStatus.design}</p>
                  </div>
                  <div className="p-3 bg-purple-500/10 rounded-full">
                    <Lightbulb className="w-5 h-5 text-purple-500" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">开发中</p>
                    <p className="text-2xl font-bold">{stats.byStatus.developing}</p>
                  </div>
                  <div className="p-3 bg-blue-500/10 rounded-full">
                    <Code2 className="w-5 h-5 text-blue-500" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">已部署</p>
                    <p className="text-2xl font-bold">{stats.byStatus.deployed}</p>
                  </div>
                  <div className="p-3 bg-green-500/10 rounded-full">
                    <Rocket className="w-5 h-5 text-green-500" />
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* 搜索和筛选 */}
          <div className="flex items-center gap-4 mb-6">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="搜索项目..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9"
              />
            </div>
            <select
              className="h-10 px-3 rounded-md border border-input bg-background"
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value as ProjectStatus | 'all')}
            >
              <option value="all">全部状态</option>
              {Object.entries(STATUS_CONFIG).map(([value, config]) => (
                <option key={value} value={value}>
                  {config.label}
                </option>
              ))}
            </select>
          </div>

          {/* 项目网格 */}
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
            </div>
          ) : filteredProjects.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <Code2 className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p className="text-base font-medium">暂无项目</p>
              <p className="text-sm mt-1 mb-5">创建新项目，或让 AI 从想法开始规划</p>
              <div className="flex items-center justify-center gap-3">
                <Button variant="outline" onClick={() => setShowIdeaForm(true)}>
                  <Lightbulb className="w-4 h-4 mr-2" /> 从想法开始
                </Button>
                <Button variant="outline" onClick={() => openProjectForm('import')}>
                  <FolderOpen className="w-4 h-4 mr-2" /> 导入现有项目
                </Button>
                <Button onClick={() => openProjectForm('create')}>
                  <Plus className="w-4 h-4 mr-2" /> 新建项目
                </Button>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredProjects.map((project) => (
                <ProjectCard
                  key={project.id}
                  project={project}
                  tasks={tasks}
                  isSelected={selectedProject?.id === project.id}
                  onSelect={setSelectedProject}
                />
              ))}
            </div>
          )}
        </div>

        {/* 项目详情侧边栏 */}
        {selectedProject && (
          <ProjectDetail
            project={selectedProject}
            tasks={tasks}
            onEdit={(project) => {
              setEditingProject(project)
              setFormData(project)
              setShowCreateForm(true)
            }}
            onDelete={(project) => setDeletingProject(project)}
          />
        )}
      </div>

      {/* 从想法创建对话框 */}
      {showIdeaForm && (
        <IdeaFormDialog
          ideaDescription={ideaDescription}
          onIdeaDescriptionChange={setIdeaDescription}
          onClose={() => setShowIdeaForm(false)}
          onFormDataChange={setFormData}
          onShowCreateForm={setShowCreateForm}
        />
      )}

      {/* 创建/编辑项目对话框 */}
      {showCreateForm && (
        <ProjectForm
          mode={projectFormMode}
          editingProject={editingProject}
          formData={formData}
          onFormDataChange={setFormData}
          onClose={() => {
            setShowCreateForm(false)
            setProjectFormMode('create')
          }}
          onSave={handleSaveProject}
        />
      )}

      {/* 删除确认对话框 */}
      <ConfirmDialog
        isOpen={!!deletingProject}
        onClose={() => setDeletingProject(null)}
        onConfirm={handleDeleteProject}
        title="删除项目"
        message={`确定要删除项目 "${deletingProject?.name}" 吗？相关任务也会被删除。此操作不可恢复。`}
        confirmText="删除"
        cancelText="取消"
        variant="danger"
      />
    </div>
  )
}
