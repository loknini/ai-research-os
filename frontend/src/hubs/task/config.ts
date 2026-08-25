import type { TaskStatus, TaskPriority } from '@/types'
import { Circle, Clock, CheckCircle2 } from 'lucide-react'

/** 任务状态展示配置（标签 / 颜色 / 图标） */
export const STATUS_CONFIG: Record<TaskStatus, { label: string; color: string; icon: typeof Circle }> = {
  todo: { label: '待办', color: 'bg-slate-500', icon: Circle },
  in_progress: { label: '进行中', color: 'bg-blue-500', icon: Clock },
  done: { label: '已完成', color: 'bg-green-500', icon: CheckCircle2 },
  archived: { label: '已归档', color: 'bg-gray-400', icon: CheckCircle2 }
}

/** 任务优先级展示配置（标签 / 颜色） */
export const PRIORITY_CONFIG: Record<TaskPriority, { label: string; color: string }> = {
  low: { label: '低', color: 'bg-slate-400' },
  medium: { label: '中', color: 'bg-blue-400' },
  high: { label: '高', color: 'bg-orange-400' },
  urgent: { label: '紧急', color: 'bg-red-500' }
}
