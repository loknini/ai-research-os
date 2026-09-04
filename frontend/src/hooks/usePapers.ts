/**
 * 跨 Hub 共享的论文数据 hook（首个 src/hooks 公共 hook）。
 *
 * 仪表盘与论文中心同调：store 仍是单一真相源；模块级 inflight 去重
 * （防 StrictMode 双 effect）+ 按空间 60s 缓存，避免来回切换重复拉取。
 */
import { useCallback, useEffect } from 'react'
import { useAppStore } from '@/stores/appStore'
import { loadLocalPapers } from '@/hubs/paper/services/papersApi'

const CACHE_TTL = 60_000

const inflight = new Map<string, Promise<void>>()
const loadedAt = new Map<string, number>()

export function usePapers() {
  const papers = useAppStore((s) => s.papers)
  const isLoading = useAppStore((s) => s.isLoadingPapers)
  const spaceKey = useAppStore((s) => s.spaceKey)

  const refresh = useCallback(async () => {
    const key = useAppStore.getState().spaceKey
    const { setPapers, setLoadingPapers } = useAppStore.getState()
    const ongoing = inflight.get(key)
    if (ongoing) {
      await ongoing
      return
    }
    let task!: Promise<void>
    task = (async () => {
      setLoadingPapers(true)
      try {
        const list = await loadLocalPapers()
        // 仅当空间未切换时写入，避免旧空间数据覆盖新空间
        if (useAppStore.getState().spaceKey === key) {
          setPapers(list)
          loadedAt.set(key, Date.now())
        }
      } catch {
        if (useAppStore.getState().spaceKey === key) setPapers([])
      } finally {
        if (useAppStore.getState().spaceKey === key) setLoadingPapers(false)
        if (inflight.get(key) === task) inflight.delete(key)
      }
    })()
    inflight.set(key, task)
    await task
  }, [])

  const ensureLoaded = useCallback(async () => {
    const key = useAppStore.getState().spaceKey
    const fresh = loadedAt.has(key) && Date.now() - (loadedAt.get(key) ?? 0) < CACHE_TTL
    if (fresh) return
    if (inflight.get(key)) {
      await inflight.get(key)
      return
    }
    await refresh()
  }, [refresh])

  useEffect(() => {
    void ensureLoaded()
  }, [ensureLoaded, spaceKey])

  return { papers, isLoading, ensureLoaded, refresh }
}
