import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useGenerationStore, type RunStatus } from '@/stores/generationStore'
import { toast } from '@/components/ui/toast'

/**
 * 全局异步生成观察器（统一 chat 流 + agent 后台运行）。
 *
 * 挂在 App 根部（常驻、不随页面切换卸载）。逻辑：
 *  - 每 2 秒巡查 store 里登记的「在途生成」；
 *  - 只关心「用户已经离开发起界面的生成」（sourcePath !== 当前路径），
 *    因为停留在该界面时，界面内会自行展示完成，无需打扰；
 *  - 当生成变成终态（completed/failed/cancelled）且尚未通知过时，弹 toast 提醒。
 *
 * 状态来源：
 *  - agent 类：watcher 轮询 GET /api/agent/runs/{id} 写回状态；
 *  - chat 类：界面内的流式 promise 在 [DONE]/错误时直接 setStatus，无需轮询。
 *
 * 若生成在「界面内」就已经终态（用户没离开），watcher 跳过 toast，但会清理掉登记项。
 */
const POLL_INTERVAL = 2000

const TERMINAL: RunStatus[] = ['completed', 'failed', 'cancelled']

function snippet(text: string, n = 40) {
  const t = (text || '').trim()
  return t.length > n ? t.slice(0, n) + '…' : t
}

export function GenerationWatcher() {
  const location = useLocation()
  const navigate = useNavigate()
  // 用 ref 持有最新路径，避免把 location 放进 effect 依赖导致频繁重启定时器
  const pathRef = useRef(location.pathname)
  pathRef.current = location.pathname

  useEffect(() => {
    const timer = setInterval(async () => {
      const { active, notified, setStatus, markNotified, unregister } = useGenerationStore.getState()
      const currentPath = pathRef.current
      const ids = Object.keys(active)
      if (ids.length === 0) return

      for (const id of ids) {
        const gen = active[id]
        let status: RunStatus = gen.status

        // agent 类需要轮询后端；chat 类状态由前端在流结束时写入，无需轮询
        if (gen.type === 'agent') {
          try {
            const resp = await fetch(`/api/agent/runs/${id}`)
            if (!resp.ok) continue
            const data = await resp.json()
            const s: RunStatus = data?.run?.status
            if (!s) continue
            setStatus(id, s)
            status = s
          } catch {
            // 网络抖动：下个周期重试
            continue
          }
        }

        if (!TERMINAL.includes(status)) continue

        // 终态：离开发起界面且未通知过 → 弹提醒（停留在该界面则不打扰）
        if (!notified[id] && gen.sourcePath !== currentPath) {
          const isOk = status === 'completed'
          const isCancel = status === 'cancelled'

          if (gen.type === 'agent') {
            const verb = isOk ? '完成' : isCancel ? '取消' : '失败'
            toast({
              title: isOk ? '✅ 多 Agent 任务完成' : isCancel ? '多 Agent 任务已取消' : '⚠️ 多 Agent 任务失败',
              description: `「${snippet(gen.label)}」已${verb}，可前往「运行历史」查看产出。`,
              variant: isOk ? 'success' : isCancel ? 'info' : 'error',
              action: { label: '查看', onClick: () => navigate('/agent-runs') },
            })
          } else {
            toast({
              title: isOk ? '💬 AI 助手已回复' : '⚠️ AI 助手回复失败',
              description: `「${snippet(gen.label)}」${isOk ? '已回复' : '未能完成'}，点击查看对话。`,
              variant: isOk ? 'success' : 'error',
              action: {
                label: '查看',
                onClick: () => navigate(gen.target ? `/chat?conv=${gen.target}` : '/chat'),
              },
            })
          }
          markNotified(id)
        }

        // 终态一律清理，避免登记项堆积
        unregister(id)
      }
    }, POLL_INTERVAL)

    return () => clearInterval(timer)
  }, [])

  return null
}
