import { useMemo } from 'react'
import type { Task, TaskStatus, TaskPriority, TaskStats } from '@/types'
import { flattenTasks, filterTaskTree } from '../utils/taskTree'

interface UseTaskDataParams {
  tasks: Task[]
  filterStatus: TaskStatus | 'all'
  filterPriority: TaskPriority | 'all'
  filterProject: string
  searchQuery: string
}

/**
 * 计算任务统计与过滤后的任务树（纯派生，无副作用）。
 * 内部复用以纯函数形式抽离的 flattenTasks / filterTaskTree。
 */
export function useTaskData({
  tasks,
  filterStatus,
  filterPriority,
  filterProject,
  searchQuery
}: UseTaskDataParams): { stats: TaskStats; filteredTasks: Task[] } {
  const stats: TaskStats = useMemo(() => {
    const allTasks = flattenTasks(tasks)
    const now = Date.now()
    return {
      total: allTasks.length,
      todo: allTasks.filter((t) => t.status === 'todo').length,
      inProgress: allTasks.filter((t) => t.status === 'in_progress').length,
      done: allTasks.filter((t) => t.status === 'done').length,
      byPriority: {
        low: allTasks.filter((t) => t.priority === 'low').length,
        medium: allTasks.filter((t) => t.priority === 'medium').length,
        high: allTasks.filter((t) => t.priority === 'high').length,
        urgent: allTasks.filter((t) => t.priority === 'urgent').length
      },
      overdue: allTasks.filter((t) => t.deadline && t.deadline < now && t.status !== 'done').length
    }
  }, [tasks])

  const filteredTasks = useMemo(() => {
    const predicate = (task: Task) => {
      if (filterStatus !== 'all' && task.status !== filterStatus) return false
      if (filterPriority !== 'all' && task.priority !== filterPriority) return false
      if (filterProject !== 'all' && task.projectId !== filterProject) return false
      if (searchQuery && !task.title.toLowerCase().includes(searchQuery.toLowerCase())) return false
      return true
    }
    return filterTaskTree(tasks, predicate)
  }, [tasks, filterStatus, filterPriority, filterProject, searchQuery])

  return { stats, filteredTasks }
}
