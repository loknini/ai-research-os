import type { Task, TaskStatus, SoftwareProject } from '@/types'

/**
 * 拉取任务列表（返回后端原始任务数组，不含树形结构）。
 * 网络错误会向上抛出，由调用方统一处理；HTTP 非 2xx 或业务失败返回空数组。
 */
export async function fetchTasks(): Promise<Task[]> {
  const response = await fetch('/api/tasks')
  if (!response.ok) return []
  const data = await response.json()
  if (!data?.success) return []
  return (data.tasks as Task[]) ?? []
}

/**
 * 拉取项目列表（用于任务关联项目）。
 */
export async function fetchProjects(): Promise<SoftwareProject[]> {
  const response = await fetch('/api/projects')
  if (!response.ok) return []
  const data = await response.json()
  if (!data?.success) return []
  return (data.projects as SoftwareProject[]) ?? []
}

/**
 * 创建或更新任务。editingTask 为 null 时创建，否则更新对应任务。
 * 返回请求是否成功（HTTP 2xx）。
 */
export async function saveTask(formData: Partial<Task>, editingTask: Task | null): Promise<boolean> {
  const payload = {
    ...formData,
    tags: formData.tags || []
  }
  const url = editingTask ? `/api/tasks/${editingTask.id}` : '/api/tasks'
  const method = editingTask ? 'PUT' : 'POST'

  const response = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  return response.ok
}

/**
 * 更新已有任务（PUT /api/tasks/:id）。
 */
export async function updateTask(taskId: string, payload: Partial<Task>): Promise<boolean> {
  const response = await fetch(`/api/tasks/${taskId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, tags: payload.tags || [] })
  })
  return response.ok
}

/**
 * 删除任务（DELETE /api/tasks/:id）。
 */
export async function deleteTaskApi(taskId: string): Promise<boolean> {
  const response = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' })
  return response.ok
}

/**
 * 仅更新任务状态（含完成时间）。
 */
export async function updateTaskStatus(
  taskId: string,
  status: TaskStatus,
  completedAt: number | null
): Promise<boolean> {
  const response = await fetch(`/api/tasks/${taskId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, completedAt })
  })
  return response.ok
}
