/**
 * The only HTTP transport used for backend API calls.
 *
 * Domain services own endpoint paths and response types; this module owns
 * authentication headers, space isolation, cancellation, connectivity and
 * response decoding. Keeping raw fetch here makes those cross-cutting rules
 * explicit and testable instead of relying on a global window.fetch patch.
 */
import { ADMIN_TOKEN_HEADER, getAdminSessionToken } from '@/services/adminAccess'
import { useAppStore } from '@/stores/appStore'

const DEFAULT_TIMEOUT_MS = 30_000

export interface ApiRequestOptions extends RequestInit {
  /** Set to null for long-lived streams. */
  timeoutMs?: number | null
}

export interface ApiErrorBody {
  error?: string
  message?: string
  detail?: string | { message?: string }
  requestId?: string
  request_id?: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly details: unknown
  readonly requestId?: string

  constructor(message: string, status: number, body?: ApiErrorBody | string | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = body
    if (body && typeof body === 'object') {
      this.code = body.error
      this.requestId = body.requestId || body.request_id
    }
  }
}

function isApiUrl(input: string | URL): boolean {
  const value = input instanceof URL ? input.href : input
  try {
    const base = new URL(typeof window === 'undefined' ? 'http://localhost' : window.location.href)
    const url = new URL(value, base)
    return url.origin === base.origin && (url.pathname === '/api' || url.pathname.startsWith('/api/'))
  } catch {
    return value === '/api' || value.startsWith('/api/')
  }
}

function mergeApiHeaders(input: string | URL, init: RequestInit): Headers {
  const headers = new Headers(init.headers)
  if (!isApiUrl(input)) return headers

  if (!headers.has('X-Space-Key')) {
    const spaceKey = useAppStore.getState().spaceKey?.trim().toLowerCase()
    if (spaceKey) headers.set('X-Space-Key', spaceKey)
  }
  if (!headers.has(ADMIN_TOKEN_HEADER)) {
    const adminToken = getAdminSessionToken()
    if (adminToken) headers.set(ADMIN_TOKEN_HEADER, adminToken)
  }
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')

  const body = init.body
  if (body != null && typeof body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  return headers
}

function createRequestSignal(
  callerSignal: AbortSignal | null | undefined,
  timeoutMs: number | null,
): { signal?: AbortSignal; cleanup: () => void } {
  // Long-lived streams must keep the caller's signal attached after response
  // headers arrive, otherwise aborting later cannot cancel body consumption.
  if (timeoutMs === null) {
    return { signal: callerSignal ?? undefined, cleanup: () => undefined }
  }

  const controller = new AbortController()
  const abortFromCaller = () => controller.abort(callerSignal?.reason)

  if (callerSignal) {
    if (callerSignal.aborted) abortFromCaller()
    else callerSignal.addEventListener('abort', abortFromCaller, { once: true })
  }
  const timer = setTimeout(() => controller.abort(new DOMException('Request timed out', 'TimeoutError')), timeoutMs)

  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timer)
      callerSignal?.removeEventListener('abort', abortFromCaller)
    },
  }
}

function reportResponse(response: Response): void {
  if (response.ok || response.status < 500) useAppStore.getState().setConnected(true)
  else useAppStore.getState().setConnected(false)
}

/** Raw response adapter for SSE, downloads and legacy callers. */
export async function apiRequest(input: string | URL, options: ApiRequestOptions = {}): Promise<Response> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...init } = options
  const { signal, cleanup } = createRequestSignal(init.signal, timeoutMs)
  try {
    const response = await fetch(input, {
      ...init,
      headers: mergeApiHeaders(input, init),
      signal,
    })
    if (isApiUrl(input)) reportResponse(response)
    return response
  } catch (error) {
    if (isApiUrl(input)) useAppStore.getState().setConnected(false)
    throw error
  } finally {
    cleanup()
  }
}

async function decodeBody(response: Response): Promise<unknown> {
  if (response.status === 204 || response.status === 205) return null
  const text = await response.text()
  if (!text) return null
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('json')) {
    try {
      return JSON.parse(text) as unknown
    } catch {
      throw new ApiError(`HTTP ${response.status}: invalid JSON response`, response.status, text.slice(0, 200))
    }
  }
  try {
    return JSON.parse(text) as unknown
  } catch {
    return text
  }
}

function errorMessage(status: number, body: unknown): string {
  if (typeof body === 'string' && body.trim()) return body.slice(0, 200)
  if (body && typeof body === 'object') {
    const value = body as ApiErrorBody
    if (typeof value.message === 'string') return value.message
    if (typeof value.detail === 'string') return value.detail
    if (value.detail && typeof value.detail === 'object' && typeof value.detail.message === 'string') {
      return value.detail.message
    }
    if (typeof value.error === 'string') return value.error
  }
  return `HTTP ${status}`
}

export async function requestJson<T>(input: string | URL, options: ApiRequestOptions = {}): Promise<T> {
  const response = await apiRequest(input, options)
  const body = await decodeBody(response)
  if (!response.ok) {
    throw new ApiError(errorMessage(response.status, body), response.status, body as ApiErrorBody | string | null)
  }
  return body as T
}

export async function requestVoid(input: string | URL, options: ApiRequestOptions = {}): Promise<void> {
  const response = await apiRequest(input, options)
  if (!response.ok) {
    const body = await decodeBody(response)
    throw new ApiError(errorMessage(response.status, body), response.status, body as ApiErrorBody | string | null)
  }
}

export async function uploadForm<T>(input: string | URL, form: FormData, options: ApiRequestOptions = {}): Promise<T> {
  return requestJson<T>(input, { ...options, method: options.method || 'POST', body: form })
}

export async function downloadBlob(
  input: string | URL,
  options: ApiRequestOptions = {},
): Promise<{ blob: Blob; response: Response }> {
  const response = await apiRequest(input, options)
  if (!response.ok) {
    const body = await decodeBody(response)
    throw new ApiError(errorMessage(response.status, body), response.status, body as ApiErrorBody | string | null)
  }
  return { blob: await response.blob(), response }
}

/** Long-lived response adapter. Stream lifetime is controlled by the caller. */
export function openEventStream(input: string | URL, options: ApiRequestOptions = {}): Promise<Response> {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'text/event-stream')
  return apiRequest(input, { ...options, headers, timeoutMs: null })
}

// Compatibility aliases while domain services move to the descriptive names.
export const apiFetch = requestJson

export type ApiResult<T> = { success: true; data: T } | { success: false; error: string; message?: string }

export async function apiFetchResult<T>(input: string | URL, options: ApiRequestOptions = {}): Promise<ApiResult<T>> {
  try {
    return { success: true, data: await requestJson<T>(input, options) }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'REQUEST_FAILED' }
  }
}
