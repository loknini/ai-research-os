/**
 * Unified API client — single point for X-Space-Key, error handling, and JSON parsing.
 * Replaces ~40 copy-pasted `fetch(...).json()` blocks across Hubs.
 */
import { useAppStore } from '@/stores/appStore'

type ApiResult<T> = { success: true; data: T } | { success: false; error: string; message?: string }

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {})
  // Inject space key if not already present and path is /api/
  if (path.includes('/api/') && !headers.has('X-Space-Key')) {
    const key = useAppStore.getState().spaceKey?.trim().toLowerCase()
    if (key) headers.set('X-Space-Key', key)
  }
  headers.set('Accept', 'application/json')
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const res = await fetch(path, { ...init, headers })
  // Try JSON, fallback to text for non-JSON errors (e.g. 502 HTML)
  const text = await res.text()
  let data: any = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`)
  }
  if (!res.ok) {
    throw new Error(data?.message || data?.error || `HTTP ${res.status}`)
  }
  return data as T
}

export async function apiFetchResult<T>(path: string, init: RequestInit = {}): Promise<ApiResult<T>> {
  try {
    const data = await apiFetch<T>(path, init)
    return { success: true, data }
  } catch (e: any) {
    return { success: false, error: e?.message || 'REQUEST_FAILED' }
  }
}
