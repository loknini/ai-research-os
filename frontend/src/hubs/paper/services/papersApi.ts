/**
 * Paper Hub 的 API 服务封装。
 * 原 monolith 中各内联 fetch 调用（37–47、141–143、185–187、216–218、279、417）
 * 统一下沉到本文件，容器只调用这些函数，不直接 fetch。
 */

import type { Paper } from '@/types'

/** 加载本地论文数据（GET /api/papers）。网络错误时返回空数组，不抛出。 */
export async function loadLocalPapers(): Promise<Paper[]> {
  try {
    const response = await fetch('/api/papers')
    if (!response.ok) throw new Error('Failed to load papers')
    const data = await response.json()
    return (data.papers as Paper[]) || []
  } catch (error) {
    console.error('Error loading papers:', error)
    return []
  }
}

export interface FetchPapersParams {
  keywords: string
  maxResults: number
}

export interface FetchPapersResult {
  papers: Paper[]
  total: number
}

/**
 * 调用后端抓取论文（POST /api/papers/fetch?...）。
 * 返回 { papers, total }，与原 monolith handleFetchPapers 读取 result.papers / result.total 的行为一致。
 */
export async function fetchPapers(params: FetchPapersParams): Promise<FetchPapersResult> {
  const searchParams = new URLSearchParams()
  searchParams.append('max', params.maxResults.toString())
  if (params.keywords.trim()) {
    searchParams.append('keywords', params.keywords.trim())
  }

  const response = await fetch(`/api/papers/fetch?${searchParams.toString()}`, {
    method: 'POST'
  })

  if (!response.ok) {
    throw new Error('Failed to fetch papers')
  }

  const result = await response.json()
  return {
    papers: (result.papers as Paper[]) || [],
    total: result.total || 0
  }
}

/** 生成论文总结（POST /api/papers/:id/summarize） */
export async function summarizePaper(
  id: string
): Promise<{ success: boolean; summary?: string; message?: string }> {
  const response = await fetch(`/api/papers/${id}/summarize`, { method: 'POST' })
  const result = await response.json()
  return {
    success: response.ok && !!result.success,
    summary: result.summary,
    message: result.message
  }
}

/** 下载论文 PDF（POST /api/papers/:arxivId/download） */
export async function downloadPaperPDF(
  arxivId: string
): Promise<{ success: boolean; path?: string; message?: string }> {
  const response = await fetch(`/api/papers/${arxivId}/download`, { method: 'POST' })
  const result = await response.json()
  return {
    success: response.ok && !!result.success,
    // 后端返回 localPath（docs/API.md 契约），前端消费方读取 path
    path: result.localPath,
    message: result.message
  }
}

/** 删除单篇论文（DELETE /api/papers/:id），返回是否成功。 */
export async function deletePaperApi(id: string): Promise<boolean> {
  const response = await fetch(`/api/papers/${id}`, { method: 'DELETE' })
  return response.ok
}

/**
 * 批量删除论文。
 * 保留原 monolith 417 行的「逐篇循环 DELETE」行为（不为性能改为并发 Promise.all），
 * 以最小化与原有请求时序/错误的差异。
 * @returns 成功删除的数量
 */
export async function batchDeletePapers(ids: string[]): Promise<number> {
  let successCount = 0
  for (const paperId of ids) {
    try {
      const response = await fetch(`/api/papers/${paperId}`, { method: 'DELETE' })
      if (response.ok) {
        successCount++
      }
    } catch (error) {
      console.error('Delete error:', error)
    }
  }
  return successCount
}
