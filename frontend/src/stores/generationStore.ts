import { create } from 'zustand'

/**
 * 统一的「异步生成观察器」全局状态。
 *
 * 覆盖两类用户发起、可能耗时、在后台跑的 AI 生成：
 *  - type='agent'：多 Agent 后台协作（在 /api/agent/runs 落库，watcher 轮询后端状态）；
 *  - type='chat'：AI 助手（ChatHub）的对话流式回复（前端在流结束时直接写状态，无需轮询）。
 *
 * watcher 组件据此在生成终态时，判断用户当前是否仍停留在「发起该生成的界面」
 * （sourcePath === 当前路由）：
 *   - 仍停留 → 由界面内自行展示完成，不打扰；
 *   - 已离开 → 弹出 toast 提醒「某个 AI 任务已完成」，并可一键跳转查看。
 */
export type GenType = 'chat' | 'agent'

export type RunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface WatchedGen {
  id: string
  type: GenType
  /** 发起该生成的界面路由（用于判断用户是否还停留在该界面） */
  sourcePath: string
  /** 摘要（需求 / 用户提问片段），用于 toast 文案 */
  label: string
  status: RunStatus
  /** 完成后「查看」要打开的对象（chat: conversationId；agent 未用） */
  target?: string
}

interface GenState {
  active: Record<string, WatchedGen>
  /** 已完成通知的生成（避免重复提醒 / 离开页面后再提醒） */
  notified: Record<string, boolean>

  /** 登记一个在途生成 */
  registerGeneration: (gen: Omit<WatchedGen, 'status'>) => void
  /** 更新观察状态（agent 由 watcher 轮询写回；chat 由界面在流结束时写入） */
  setStatus: (id: string, status: RunStatus) => void
  /** 界面内已就地展示终态，标记无需再 toast */
  markNotified: (id: string) => void
  /** 从观察列表移除 */
  unregister: (id: string) => void
}

export const useGenerationStore = create<GenState>((set) => ({
  active: {},
  notified: {},

  registerGeneration: (gen) =>
    set((s) => ({
      active: {
        ...s.active,
        [gen.id]: { ...gen, status: 'running' },
      },
    })),

  setStatus: (id, status) =>
    set((s) => {
      const cur = s.active[id]
      if (!cur) return s
      return { active: { ...s.active, [id]: { ...cur, status } } }
    }),

  markNotified: (id) =>
    set((s) => ({ notified: { ...s.notified, [id]: true } })),

  unregister: (id) =>
    set((s) => {
      const nextActive = { ...s.active }
      const nextNotified = { ...s.notified }
      delete nextActive[id]
      delete nextNotified[id]
      return { active: nextActive, notified: nextNotified }
    }),
}))
