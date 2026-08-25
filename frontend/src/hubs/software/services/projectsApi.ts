import type { SoftwareProject } from '@/types'

/**
 * 获取项目列表（对应原 loadData 中的 fetch('/api/projects')）
 */
export async function fetchProjects(): Promise<Response> {
  return fetch('/api/projects')
}

/**
 * 获取任务列表（对应原 loadData 中的 fetch('/api/tasks')）
 */
export async function fetchTasks(): Promise<Response> {
  return fetch('/api/tasks')
}

/**
 * 新建项目（对应原 handleSaveProject 中的 POST 段）
 */
export async function saveProject(formData: Partial<SoftwareProject>): Promise<Response> {
  return fetch('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formData)
  })
}

/**
 * 更新项目（对应原 handleSaveProject 中的 PUT 段）
 */
export async function updateProject(
  id: string,
  formData: Partial<SoftwareProject>
): Promise<Response> {
  return fetch(`/api/projects/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formData)
  })
}

/**
 * 新建项目成功后自动创建 3 条默认任务（对应原 handleSaveProject 中 159–171 行逻辑）
 */
export async function createDefaultTasks(projectId: string): Promise<void> {
  const defaultTasks = [
    { title: '需求分析', description: '整理项目需求', priority: 'high' },
    { title: '技术选型', description: '确定技术栈', priority: 'high' },
    { title: '环境搭建', description: '初始化开发环境', priority: 'medium' }
  ]

  for (const task of defaultTasks) {
    await fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...task,
        projectId,
        status: 'todo',
        tags: ['software'],
        aiSuggested: true
      })
    })
  }
}

/**
 * 删除项目（对应原 handleDeleteProject 中的 DELETE 段）
 */
export async function deleteProjectApi(id: string): Promise<Response> {
  return fetch(`/api/projects/${id}`, { method: 'DELETE' })
}
