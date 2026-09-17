import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const transportState = vi.hoisted(() => ({
  spaceKey: '  Lab-A  ',
  adminToken: 'admin-secret',
  connected: false,
  setConnected: vi.fn((value: boolean) => {
    transportState.connected = value
  }),
}))

vi.mock('@/stores/appStore', () => ({
  useAppStore: {
    getState: () => ({
      spaceKey: transportState.spaceKey,
      setConnected: transportState.setConnected,
    }),
  },
}))

vi.mock('@/services/adminAccess', () => ({
  ADMIN_TOKEN_HEADER: 'X-Admin-Token',
  getAdminSessionToken: () => transportState.adminToken,
}))

import { ApiError, apiRequest, downloadBlob, openEventStream, requestJson, uploadForm } from './api'

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

describe('API transport', () => {
  beforeEach(() => {
    transportState.spaceKey = '  Lab-A  '
    transportState.adminToken = 'admin-secret'
    transportState.connected = false
    transportState.setConnected.mockClear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('injects normalized isolation and admin headers into API requests', async () => {
    const request = vi.fn(async (_input: string | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers)
      expect(headers.get('X-Space-Key')).toBe('lab-a')
      expect(headers.get('X-Admin-Token')).toBe('admin-secret')
      expect(headers.get('Accept')).toBe('application/json')
      expect(headers.get('X-Custom')).toBe('kept')
      return jsonResponse({ ok: true })
    })
    vi.stubGlobal('fetch', request)

    await apiRequest('/api/example', { headers: { 'X-Custom': 'kept' } })

    expect(request).toHaveBeenCalledOnce()
    expect(transportState.setConnected).toHaveBeenCalledWith(true)
  })

  it('respects explicit authentication headers', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_input: string | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers)
      expect(headers.get('X-Space-Key')).toBe('override-space')
      expect(headers.get('X-Admin-Token')).toBe('override-admin')
      return jsonResponse({ ok: true })
    }))

    await apiRequest('/api/example', {
      headers: { 'X-Space-Key': 'override-space', 'X-Admin-Token': 'override-admin' },
    })
  })

  it('never sends local credentials to a cross-origin API-looking URL', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_input: string | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers)
      expect(headers.has('X-Space-Key')).toBe(false)
      expect(headers.has('X-Admin-Token')).toBe(false)
      return jsonResponse({ ok: true })
    }))

    await apiRequest('https://example.com/api/public')
    expect(transportState.setConnected).not.toHaveBeenCalled()
  })

  it('sets JSON content type for string bodies but not FormData', async () => {
    const observed: Array<string | null> = []
    vi.stubGlobal('fetch', vi.fn(async (_input: string | URL, init?: RequestInit) => {
      observed.push(new Headers(init?.headers).get('Content-Type'))
      return jsonResponse({ success: true })
    }))

    await requestJson('/api/json', { method: 'POST', body: JSON.stringify({ value: 1 }) })
    await uploadForm('/api/upload', new FormData())

    expect(observed).toEqual(['application/json', null])
  })

  it('decodes JSON, empty responses and blob downloads', async () => {
    const responses = [
      jsonResponse({ value: 42 }),
      new Response(null, { status: 204 }),
      new Response('archive', { status: 200, headers: { 'Content-Type': 'application/zip' } }),
    ]
    vi.stubGlobal('fetch', vi.fn(async () => responses.shift() as Response))

    await expect(requestJson<{ value: number }>('/api/value')).resolves.toEqual({ value: 42 })
    await expect(requestJson<null>('/api/empty')).resolves.toBeNull()
    const result = await downloadBlob('/api/archive')
    await expect(result.blob.text()).resolves.toBe('archive')
  })

  it('raises a structured ApiError and marks 5xx responses disconnected', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(
      { error: 'BROKEN', message: 'backend failed', request_id: 'req-7' },
      { status: 503 },
    )))

    const error = await requestJson('/api/fail').catch((reason: unknown) => reason)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 503, code: 'BROKEN', message: 'backend failed', requestId: 'req-7' })
    expect(transportState.setConnected).toHaveBeenCalledWith(false)
  })

  it('preserves caller cancellation and reports transport failures', async () => {
    const controller = new AbortController()
    vi.stubGlobal('fetch', vi.fn((_input: string | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true })
    })))

    const pending = apiRequest('/api/slow', { signal: controller.signal, timeoutMs: null })
    controller.abort(new DOMException('cancelled', 'AbortError'))

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    expect(transportState.setConnected).toHaveBeenCalledWith(false)
  })

  it('aborts a request when its timeout expires', async () => {
    vi.stubGlobal('fetch', vi.fn((_input: string | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true })
    })))

    const error = await apiRequest('/api/slow', { timeoutMs: 5 }).catch((reason: unknown) => reason)

    expect(error).toMatchObject({ name: 'TimeoutError' })
    expect(transportState.setConnected).toHaveBeenCalledWith(false)
  })

  it('uses the event-stream accept header without a transport timeout', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_input: string | URL, init?: RequestInit) => {
      expect(new Headers(init?.headers).get('Accept')).toBe('text/event-stream')
      return new Response('data: [DONE]\n\n')
    }))

    await expect(openEventStream('/api/events')).resolves.toBeInstanceOf(Response)
  })

  it('keeps caller cancellation active after an event stream is established', async () => {
    const controller = new AbortController()
    vi.stubGlobal('fetch', vi.fn(async (_input: string | URL, init?: RequestInit) => {
      const stream = new ReadableStream({
        start(streamController) {
          init?.signal?.addEventListener(
            'abort',
            () => streamController.error(init.signal?.reason),
            { once: true },
          )
        },
      })
      return new Response(stream)
    }))

    const response = await openEventStream('/api/events', { signal: controller.signal })
    const read = response.body!.getReader().read()
    controller.abort(new DOMException('cancelled', 'AbortError'))

    await expect(read).rejects.toMatchObject({ name: 'AbortError' })
  })
})
