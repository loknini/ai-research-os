import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { CheckCircle2, Sparkles } from 'lucide-react'
import type { SoftwareProject, Task } from '@/types'
import { STATUS_CONFIG } from '../config'

interface ProjectCardProps {
  project: SoftwareProject
  tasks: Task[]
  isSelected: boolean
  onSelect: (project: SoftwareProject) => void
}

/** 项目卡片（对应原容器内 renderProjectCard 207–271 行） */
export function ProjectCard({ project, tasks, isSelected, onSelect }: ProjectCardProps) {
  const statusConfig = STATUS_CONFIG[project.status]
  const projectTasks = tasks.filter((t) => t.projectId === project.id)
  const completedTasks = projectTasks.filter((t) => t.status === 'done').length
  const StatusIcon = statusConfig.icon

  return (
    <Card
      className={`cursor-pointer transition-all hover:shadow-md ${
        isSelected ? 'ring-2 ring-primary' : ''
      }`}
      onClick={() => onSelect(project)}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <div className={`p-2 rounded-lg ${statusConfig.color} bg-opacity-10`}>
              <StatusIcon className={`w-5 h-5 ${statusConfig.color.replace('bg-', 'text-')}`} />
            </div>
            <div>
              <CardTitle className="text-lg">{project.name}</CardTitle>
              <CardDescription className="text-xs mt-0.5">
                创建于 {new Date(project.createdAt).toLocaleDateString('zh-CN')}
              </CardDescription>
            </div>
          </div>
          <Badge className={statusConfig.color}>{statusConfig.label}</Badge>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <p className="text-sm text-muted-foreground line-clamp-2 mb-3">
          {project.description || '暂无描述'}
        </p>

        {project.techStack && project.techStack.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-3">
            {project.techStack.slice(0, 4).map((tech) => (
              <span key={tech} className="text-xs px-2 py-0.5 bg-muted rounded-full">
                {tech}
              </span>
            ))}
            {project.techStack.length > 4 && (
              <span className="text-xs px-2 py-0.5 bg-muted rounded-full">
                +{project.techStack.length - 4}
              </span>
            )}
          </div>
        )}

        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span className="flex items-center gap-1">
            <CheckCircle2 className="w-4 h-4" />
            {completedTasks}/{projectTasks.length} 任务
          </span>
          {project.aiGeneratedCode && (
            <Sparkles className="w-4 h-4 text-amber-500" />
          )}
        </div>
      </CardContent>
    </Card>
  )
}
