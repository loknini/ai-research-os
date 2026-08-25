import type { Task, TaskStatus, SoftwareProject } from '@/types'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { CheckCircle2, Circle, Calendar, Folder, History, Edit2, Trash2, Sparkles } from 'lucide-react'
import { PRIORITY_CONFIG } from '../config'

export interface TaskItemProps {
  task: Task
  depth?: number
  projects: SoftwareProject[]
  onStatusChange: (task: Task, newStatus: TaskStatus) => void
  onEdit: (task: Task) => void
  onDelete: (task: Task) => void
  onShowHistory: (taskId: string) => void
}

/**
 * 递归渲染单个任务及其子任务（原 index.tsx 中的 renderTask）。
 * 组件不反向依赖容器，所有交互通过回调上抛。
 */
export default function TaskItem({
  task,
  depth = 0,
  projects,
  onStatusChange,
  onEdit,
  onDelete,
  onShowHistory
}: TaskItemProps) {
  return (
    <div className={depth > 0 ? 'ml-6 border-l-2 border-border pl-4' : ''}>
      <div className="group flex items-center gap-3 p-3 rounded-lg hover:bg-muted/50 transition-colors">
        <button
          onClick={() => onStatusChange(task, task.status === 'done' ? 'todo' : 'done')}
          className="flex-shrink-0"
        >
          {task.status === 'done' ? (
            <CheckCircle2 className="w-5 h-5 text-green-500" />
          ) : (
            <Circle className="w-5 h-5 text-muted-foreground hover:text-primary" />
          )}
        </button>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`font-medium truncate ${task.status === 'done' ? 'line-through text-muted-foreground' : ''}`}>
              {task.title}
            </span>
            {task.aiSuggested && (
              <Sparkles className="w-3.5 h-3.5 text-amber-500" />
            )}
          </div>
          {task.description && (
            <p className="text-sm text-muted-foreground line-clamp-1">{task.description}</p>
          )}
          <div className="flex items-center gap-2 mt-1">
            <Badge variant="secondary" className={`text-xs ${PRIORITY_CONFIG[task.priority].color} text-white`}>
              {PRIORITY_CONFIG[task.priority].label}
            </Badge>
            {task.deadline && (
              <span className={`text-xs flex items-center gap-1 ${
                task.deadline < Date.now() && task.status !== 'done' ? 'text-red-500' : 'text-muted-foreground'
              }`}>
                <Calendar className="w-3 h-3" />
                {new Date(task.deadline).toLocaleDateString('zh-CN')}
              </span>
            )}
            {task.projectId && (
              <span className="text-xs flex items-center gap-1 text-muted-foreground">
                <Folder className="w-3 h-3" />
                {projects.find((p) => p.id === task.projectId)?.name || '未知项目'}
              </span>
            )}
            {task.tags?.map((tag) => (
              <span key={tag} className="text-xs bg-muted px-1.5 py-0.5 rounded">{tag}</span>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onShowHistory(task.id)}
            title="版本历史"
          >
            <History className="w-4 h-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onEdit(task)}
          >
            <Edit2 className="w-4 h-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-red-500 hover:text-red-600"
            onClick={() => onDelete(task)}
          >
            <Trash2 className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {task.subTasks?.map((subTask) => (
        <TaskItem
          key={subTask.id}
          task={subTask}
          depth={depth + 1}
          projects={projects}
          onStatusChange={onStatusChange}
          onEdit={onEdit}
          onDelete={onDelete}
          onShowHistory={onShowHistory}
        />
      ))}
    </div>
  )
}
