// 全局 fetch 监控：把全站对 /api 的请求收口到这一层，
// 用真实流量驱动侧边栏「后端状态」灯，取代原先每 5 秒的 healthz 轮询。
// - 任意 /api 请求成功（res.ok）→ 视为已连接
// - 任意 /api 请求网络失败（fetch 抛错，如后端崩溃/未启动）→ 视为断开
// - 任意 /api 请求返回 5xx / 502 / 503 / 504（开发态 Vite 代理也可能返回 500）→ 视为断开
// 注意：HTTP 4xx 不算断开（后端活着，只是请求有误），不更新状态。
import { useAppStore } from '@/stores/appStore'

let installed = false

export function installApiMonitor(): void {
  if (installed || typeof window === 'undefined') return
  installed = true

  const nativeFetch = window.fetch.bind(window)

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : input.url
    const isApi = url.includes('/api/')

    // 单一收口：仅对 /api/ 请求注入 X-Space-Key（归一化与后端一致：trim + lower）。
    // 无 key 时不带该头（此时 SpaceGate 已保证先引导，不会发出缺失请求）。
    if (isApi) {
      const key = useAppStore.getState().spaceKey
      if (key && key.trim()) {
        init = {
          ...init,
          headers: {
            ...(init?.headers || {}),
            'X-Space-Key': key.trim().toLowerCase(),
          },
        }
      }
    }

    try {
      const res = await nativeFetch(input, init)
      if (isApi) {
        if (res.ok) {
          useAppStore.getState().setConnected(true)
        } else if (res.status >= 500) {
          // 后端进程断开或代理层错误（如 Vite 代理返回 500/502/504）
          useAppStore.getState().setConnected(false)
        }
      }
      return res
    } catch (err) {
      if (isApi) {
        useAppStore.getState().setConnected(false)
      }
      throw err
    }
  }
}
