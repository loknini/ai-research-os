/**
 * Cron 定时任务 API 客户端
 */
import type { CronJob, CronRunHistory } from '@/types'

export async function fetchCronJobs(): Promise<CronJob[]> {
  const res = await fetch('/api/cron/jobs')
  const data = await res.json()
  return data.jobs || []
}

export async function createCronJob(body: {
  name: string
  description?: string
  schedule: string
  command?: string
  jobType: string
  payload?: Record<string, any> | null
  enabled?: boolean
}): Promise<CronJob> {
  const res = await fetch('/api/cron/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  if (!data.success) throw new Error(data.message || '创建失败')
  return data.job
}

export async function toggleCronJob(jobId: string): Promise<CronJob> {
  const res = await fetch(`/api/cron/jobs/${jobId}/toggle`, { method: 'POST' })
  const data = await res.json()
  if (!data.success) throw new Error(data.message || '操作失败')
  return data.job
}

export async function runCronJob(jobId: string): Promise<{ status: string; output: string }> {
  const res = await fetch(`/api/cron/jobs/${jobId}/run`, { method: 'POST' })
  const data = await res.json()
  if (!data.success) throw new Error(data.message || '运行失败')
  return { status: data.status, output: data.output }
}

export async function deleteCronJob(jobId: string): Promise<void> {
  const res = await fetch(`/api/cron/jobs/${jobId}`, { method: 'DELETE' })
  const data = await res.json()
  if (!data.success) throw new Error(data.message || '删除失败')
}

export async function fetchCronHistory(jobId?: string): Promise<CronRunHistory[]> {
  const url = jobId
    ? `/api/cron/jobs/${jobId}/history`
    : '/api/cron/history'
  const res = await fetch(url)
  const data = await res.json()
  return data.history || []
}
