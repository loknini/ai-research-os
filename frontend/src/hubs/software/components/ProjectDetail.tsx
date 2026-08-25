import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Edit2, Trash2, Cpu, Layout, Clock, CheckCircle2 } from 'lucide-react'
import type { SoftwareProject, Task } from '@/types'
import { STATUS_CONFIG } from '../config'

interface ProjectDetailProps {
  project: SoftwareProject
  tasks: Task[]
  onEdit: (project: SoftwareProject) => void
  onDelete: (project: SoftwareProject) => void
}

/** 项目详情侧边栏（对应原容器内 399–528 行） */
export function ProjectDetail({ project, tasks, onEdit, onDelete }: ProjectDetailProps) {
  return (
    <div className="w-96 border-l bg-muted/30 overflow-y-auto">
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <Badge className={STATUS_CONFIG[project.status].color}>
            {STATUS_CONFIG[project.status].label}
          </Badge>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onEdit(project)}
            >
              <Edit2 className="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-red-500"
              onClick={() => onDelete(project)}
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          </div>
        </div>

        <h2 className="text-xl font-bold mb-2">{project.name}</h2>
        <p className="text-sm text-muted-foreground mb-6">
          {project.description || '暂无描述'}
        </p>

        {/* 技术栈 */}
        <div className="mb-6">
          <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
            <Cpu className="w-4 h-4" />
            技术栈
          </h3>
          <div className="flex flex-wrap gap-2">
            {project.techStack?.map((tech) => (
              <span key={tech} className="text-xs px-2 py-1 bg-background rounded-md border">
                {tech}
              </span>
            ))}
          </div>
        </div>

        {/* 功能模块 */}
        {project.features && project.features.length > 0 && (
          <div className="mb-6">
            <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
              <Layout className="w-4 h-4" />
              功能模块
            </h3>
            <div className="space-y-2">
              {project.features.map((feature) => (
                <div key={feature.id} className="p-2 bg-background rounded-lg border">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-sm">{feature.name}</span>
                    <Badge
                      variant={feature.status === 'done' ? 'default' : 'secondary'}
                      className="text-xs"
                    >
                      {feature.status === 'done' ? '完成' : '待办'}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">{feature.description}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 里程碑 */}
        {project.milestones && project.milestones.length > 0 && (
          <div className="mb-6">
            <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
              <Clock className="w-4 h-4" />
              里程碑
            </h3>
            <div className="space-y-2">
              {project.milestones.map((milestone, index) => (
                <div key={milestone.id} className="flex items-start gap-3">
                  <div
                    className={`w-6 h-6 rounded-full flex items-center justify-center text-xs ${
                      milestone.status === 'completed'
                        ? 'bg-green-500 text-white'
                        : milestone.status === 'in_progress'
                          ? 'bg-blue-500 text-white'
                          : 'bg-muted text-muted-foreground'
                    }`}
                  >
                    {index + 1}
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-medium">{milestone.name}</p>
                    <p className="text-xs text-muted-foreground">{milestone.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 相关任务 */}
        <div>
          <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4" />
            相关任务
          </h3>
          {(() => {
            const projectTasks = tasks.filter((t) => t.projectId === project.id)
            if (projectTasks.length === 0) {
              return <p className="text-sm text-muted-foreground">暂无相关任务</p>
            }
            return (
              <div className="space-y-2">
                {projectTasks.map((task) => (
                  <div
                    key={task.id}
                    className="flex items-center gap-2 p-2 bg-background rounded-lg border"
                  >
                    <div
                      className={`w-2 h-2 rounded-full ${
                        task.status === 'done'
                          ? 'bg-green-500'
                          : task.status === 'in_progress'
                            ? 'bg-blue-500'
                            : 'bg-slate-300'
                      }`}
                    />
                    <span className="text-sm flex-1 truncate">{task.title}</span>
                  </div>
                ))}
              </div>
            )
          })()}
        </div>
      </div>
    </div>
  )
}
