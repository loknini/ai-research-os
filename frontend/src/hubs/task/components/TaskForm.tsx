import type { Task, TaskStatus, TaskPriority, SoftwareProject } from '@/types'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { STATUS_CONFIG, PRIORITY_CONFIG } from '../config'

export interface TaskFormProps {
  isOpen: boolean
  editingTask: Task | null
  formData: Partial<Task>
  setFormData: (data: Partial<Task>) => void
  tagInput: string
  setTagInput: (value: string) => void
  handleAddTag: () => void
  handleSaveTask: () => void
  onCancel: () => void
  projects: SoftwareProject[]
}

/**
 * 新建 / 编辑任务表单（原 index.tsx 中的添加/编辑对话框）。
 * 纯展示 + 受控表单，状态与保存逻辑由容器通过 props 注入。
 */
export default function TaskForm({
  isOpen,
  editingTask,
  formData,
  setFormData,
  tagInput,
  setTagInput,
  handleAddTag,
  handleSaveTask,
  onCancel,
  projects
}: TaskFormProps) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <Card className="w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <CardHeader>
          <CardTitle>{editingTask ? '编辑任务' : '新建任务'}</CardTitle>
          <CardDescription>
            {editingTask ? '更新任务信息' : '创建一个新的待办事项'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-2 block">任务标题 *</label>
            <Input
              placeholder="输入任务标题..."
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
            />
          </div>

          <div>
            <label className="text-sm font-medium mb-2 block">描述</label>
            <Input
              placeholder="添加详细描述..."
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-2 block">状态</label>
              <select
                className="w-full h-10 px-3 rounded-md border border-input bg-background"
                value={formData.status}
                onChange={(e) => setFormData({ ...formData, status: e.target.value as TaskStatus })}
              >
                {Object.entries(STATUS_CONFIG).map(([value, config]) => (
                  <option key={value} value={value}>{config.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">优先级</label>
              <select
                className="w-full h-10 px-3 rounded-md border border-input bg-background"
                value={formData.priority}
                onChange={(e) => setFormData({ ...formData, priority: e.target.value as TaskPriority })}
              >
                {Object.entries(PRIORITY_CONFIG).map(([value, config]) => (
                  <option key={value} value={value}>{config.label}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="text-sm font-medium mb-2 block">关联项目</label>
            <select
              className="w-full h-10 px-3 rounded-md border border-input bg-background"
              value={formData.projectId || ''}
              onChange={(e) => setFormData({ ...formData, projectId: e.target.value || undefined })}
            >
              <option value="">无</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-sm font-medium mb-2 block">标签</label>
            <div className="flex gap-2 mb-2">
              <Input
                placeholder="添加标签..."
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), handleAddTag())}
              />
              <Button type="button" onClick={handleAddTag}>添加</Button>
            </div>
            <div className="flex flex-wrap gap-2">
              {formData.tags?.map((tag) => (
                <Badge key={tag} variant="secondary" className="cursor-pointer" onClick={() => {
                  setFormData({ ...formData, tags: formData.tags?.filter((t) => t !== tag) })
                }}>
                  {tag} ×
                </Badge>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-4">
            <Button variant="outline" onClick={onCancel}>
              取消
            </Button>
            <Button onClick={handleSaveTask}>
              {editingTask ? '保存' : '创建'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
