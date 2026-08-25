import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { SoftwareProject, ProjectStatus } from '@/types'
import { STATUS_CONFIG, TECH_STACK_OPTIONS } from '../config'

interface ProjectFormProps {
  mode?: 'create' | 'import'
  editingProject: SoftwareProject | null
  formData: Partial<SoftwareProject>
  onFormDataChange: (data: Partial<SoftwareProject>) => void
  onClose: () => void
  onSave: () => void
}

/** 新建/编辑/导入项目表单对话框（对应原容器内 596–696 行） */
export function ProjectForm({
  mode = 'create',
  editingProject,
  formData,
  onFormDataChange,
  onClose,
  onSave
}: ProjectFormProps) {
  const isEdit = !!editingProject
  const title = isEdit ? '编辑项目' : mode === 'import' ? '导入现有项目' : '新建项目'
  const description = isEdit
    ? '更新项目信息'
    : mode === 'import'
      ? '录入本地已有项目的路径与基本信息'
      : '创建一个新的软件项目'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <Card className="w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-2 block">项目名称 *</label>
            <Input
              placeholder="输入项目名称..."
              value={formData.name}
              onChange={(e) => onFormDataChange({ ...formData, name: e.target.value })}
            />
          </div>

          <div>
            <label className="text-sm font-medium mb-2 block">项目描述</label>
            <textarea
              className="w-full min-h-[80px] p-3 rounded-md border border-input bg-background resize-none"
              placeholder="描述项目的目标和用途..."
              value={formData.description}
              onChange={(e) => onFormDataChange({ ...formData, description: e.target.value })}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-2 block">当前状态</label>
              <select
                className="w-full h-10 px-3 rounded-md border border-input bg-background"
                value={formData.status}
                onChange={(e) =>
                  onFormDataChange({ ...formData, status: e.target.value as ProjectStatus })
                }
              >
                {Object.entries(STATUS_CONFIG).map(([value, config]) => (
                  <option key={value} value={value}>
                    {config.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">本地路径</label>
              <Input
                placeholder="项目本地路径..."
                value={formData.localPath || ''}
                onChange={(e) => onFormDataChange({ ...formData, localPath: e.target.value })}
              />
            </div>
          </div>

          <div>
            <label className="text-sm font-medium mb-2 block">GitHub 仓库</label>
            <Input
              placeholder="https://github.com/..."
              value={formData.githubUrl || ''}
              onChange={(e) => onFormDataChange({ ...formData, githubUrl: e.target.value })}
            />
          </div>

          <div>
            <label className="text-sm font-medium mb-2 block">技术栈</label>
            <div className="flex flex-wrap gap-2 mb-2">
              {TECH_STACK_OPTIONS.map((tech) => {
                const isSelected = formData.techStack?.includes(tech)
                return (
                  <button
                    key={tech}
                    onClick={() => {
                      if (isSelected) {
                        onFormDataChange({
                          ...formData,
                          techStack: formData.techStack?.filter((t) => t !== tech)
                        })
                      } else {
                        onFormDataChange({
                          ...formData,
                          techStack: [...(formData.techStack || []), tech]
                        })
                      }
                    }}
                    className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                      isSelected
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'bg-background hover:bg-muted'
                    }`}
                  >
                    {tech}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-4">
            <Button variant="outline" onClick={onClose}>
              取消
            </Button>
            <Button onClick={onSave}>
              {editingProject ? '保存' : mode === 'import' ? '导入' : '创建'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
