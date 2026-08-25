import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useAppStore } from '@/stores/appStore'

// 与后端 deps.MIN_KEY_LEN 保持一致。
const MIN_KEY_LEN = 4

/**
 * 首屏空间口令守卫。
 *
 * - 未选择空间时渲染全屏弹层，拦截应用渲染（保证正常流程不会向后端发出缺失
 *   X-Space-Key 的请求）。
 * - 解析 URL `?space=` 参数，分享链接可直达进入对应空间。
 * - 选择后写入并持久化 spaceKey（由 apiMonitor 统一归一化为 X-Space-Key 透传）。
 */
export function SpaceGate({ children }: { children: ReactNode }) {
  const spaceKey = useAppStore((s) => s.spaceKey)
  const setSpace = useAppStore((s) => s.setSpace)
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | undefined>()

  // 解析 ?space= 自动进入（分享链接直达），仅执行一次。
  const bootstrapped = useRef(false)
  useEffect(() => {
    if (bootstrapped.current) return
    bootstrapped.current = true
    const sp = new URLSearchParams(window.location.search).get('space')
    if (sp && sp.trim()) setSpace(sp.trim())
  }, [setSpace])

  if (spaceKey && spaceKey.trim()) {
    return <>{children}</>
  }

  const submit = () => {
    const k = input.trim()
    if (k.length < MIN_KEY_LEN) {
      setError(`空间口令至少需要 ${MIN_KEY_LEN} 个字符`)
      return
    }
    setSpace(k)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-lg border bg-card p-6 shadow-lg">
        <h2 className="text-xl font-bold">进入工作空间</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          输入一个空间口令（至少 {MIN_KEY_LEN} 个字符，可含中文 / 符号）。同一口令在任意设备上互通同一份数据；
          不同口令之间数据相互隔离。
        </p>
        <input
          autoFocus
          value={input}
          onChange={(e) => {
            setInput(e.target.value)
            setError(undefined)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit()
          }}
          placeholder="例如：my-lab 或 我的实验室"
          className="mt-4 w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
        />
        {error && <p className="mt-2 text-sm text-red-500">{error}</p>}
        <button
          onClick={submit}
          className="mt-4 w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          进入
        </button>
        <p className="mt-3 text-xs text-muted-foreground">
          提示：不要把口令取为 <code>__default__</code>（那是系统存量空间）。
        </p>
      </div>
    </div>
  )
}

export default SpaceGate
