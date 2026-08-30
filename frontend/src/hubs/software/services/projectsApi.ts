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

export async function validateWorkspace(id: string): Promise<any> {
  const response = await fetch(`/api/projects/${id}/workspace/validate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.message || '工作区校验失败')
  return data.workspace
}

export async function fetchDevelopmentRuns(id: string): Promise<any[]> {
  const response = await fetch(`/api/projects/${id}/development-runs`)
  const data = await response.json()
  if (!response.ok) throw new Error(data.message || '运行历史加载失败')
  return data.runs || []
}

export async function createDevelopmentRun(id: string, payload: Record<string, unknown>): Promise<string> {
  const response = await fetch(`/api/projects/${id}/development-runs`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.message || '研发运行创建失败')
  return data.runId
}

export async function fetchDevelopmentRun(id: string): Promise<any> {
  const response = await fetch(`/api/development/runs/${id}`)
  const data = await response.json()
  if (!response.ok) throw new Error(data.message || '研发运行加载失败')
  return data
}

export async function fetchDevelopmentDiff(id: string): Promise<any> {
  const response = await fetch(`/api/development/runs/${id}/diff`)
  const data = await response.json()
  if (!response.ok) throw new Error(data.message || '差异加载失败')
  return data
}

export async function cancelDevelopmentRun(id: string): Promise<void> {
  const response = await fetch(`/api/development/runs/${id}/cancel`, { method: 'POST' })
  if (!response.ok) throw new Error('取消失败')
}

export async function continueDevelopmentRun(id: string, feedback = ''): Promise<void> {
  const response = await fetch(`/api/development/runs/${id}/continue`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ additionalIterations: 4, additionalMinutes: 30, feedback })
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.message || '继续运行失败')
}

export async function applyDevelopmentRun(id: string, baseRevision: string, diffDigest: string): Promise<any> {
  const response = await fetch(`/api/development/runs/${id}/apply`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ baseRevision, diffDigest })
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.message || '应用失败')
  return data
}
