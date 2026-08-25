import { streamChatCompletion, addMessageAPI } from './chatApi'
import { useGenerationStore } from '@/stores/generationStore'
import { generateId } from '@/utils'
import type { Message, ReasoningStep, ToolResult, RagSource } from '../types'

export type GenStatus = 'running' | 'completed' | 'failed' | 'cancelled'

export interface ActiveGeneration {
  conversationId: string
  genId: string
  status: GenStatus
  streamingContent: string
  reasoningSteps: ReasoningStep[]
  contextInfo?: { estimated_tokens: number; limit: number; compressed: boolean }
  ragSources?: RagSource[]
  hadError: boolean
  finalMessage?: Message
}

/**
 * 聊天生成的「模块级单例」运行器。
 *
 * 目的：把 AI 流式回复从 ChatHub 组件生命周期里解耦出来。
 *  - 组件卸载（用户切到别的 Hub）不再 abort 生成 → 回复在后台继续跑完；
 *  - 后端已落库（addMessageAPI），完成后全局「生成观察器」(generationStore + watcher)
 *    在用户已离开 /chat 时弹「AI 助手已回复」提醒，点击「查看」跳回该会话；
 *  - 用户切回时，组件订阅本单例，接管实时流式状态（思考过程/正文）并在终态时刷新详情。
 *
 * 每个 conversationId 同时只跑一个生成（锁）。
 */

const TERMINAL_TTL = 8000

class ChatGenerationManager {
  private active = new Map<string, ActiveGeneration>()
  private subscribers = new Map<string, Set<() => void>>()
  private controllers = new Map<string, AbortController>()
  private timers = new Map<string, ReturnType<typeof setTimeout>>()

  /** 是否正在跑（running）。 */
  isActive(conversationId: string): boolean {
    const g = this.active.get(conversationId)
    return !!g && g.status === 'running'
  }

  /** 取当前活动生成（含终态残留），用于组件挂载时接管实时状态。 */
  getActive(conversationId: string): ActiveGeneration | undefined {
    return this.active.get(conversationId)
  }

  /** 订阅某会话的生成状态变化；返回取消订阅函数。 */
  subscribe(conversationId: string, cb: () => void): () => void {
    if (!this.subscribers.has(conversationId)) {
      this.subscribers.set(conversationId, new Set())
    }
    this.subscribers.get(conversationId)!.add(cb)
    return () => {
      this.subscribers.get(conversationId)?.delete(cb)
    }
  }

  /** 主动取消（目前 UI 未接取消按钮，保留 API）。 */
  cancel(conversationId: string) {
    this.controllers.get(conversationId)?.abort()
  }

  /** 立即清理某会话的「活动生成状态」（终态接管后由订阅者调用）。
   *
   * 注意：此处**不**删除 subscribers。订阅者的生命周期由组件挂载 /
   * 切换会话时的 subscribe / 返回的取消函数管理；若在此处误删，
   * 会导致「首次生成完成后立即点重新生成」时新生成没有任何订阅者，
   * UI 收不到流式更新与终态刷新（表现：旧回复被本地移除、新回复不出现）。
   * 仅重置生成运行时状态，subscribers 保持不动。
   */
  clear(conversationId: string) {
    const t = this.timers.get(conversationId)
    if (t) {
      clearTimeout(t)
      this.timers.delete(conversationId)
    }
    this.active.delete(conversationId)
    this.controllers.delete(conversationId)
  }

  private notify(conversationId: string) {
    this.subscribers.get(conversationId)?.forEach((cb) => cb())
  }

  private scheduleClear(conversationId: string) {
    const existing = this.timers.get(conversationId)
    if (existing) clearTimeout(existing)
    this.timers.set(
      conversationId,
      setTimeout(() => {
        this.active.delete(conversationId)
        this.timers.delete(conversationId)
      }, TERMINAL_TTL)
    )
  }

  /** 发起一次生成。
   *
   * 返回本次生成的 Promise（在流式结束 / 出错 / 取消时 resolve），便于调用方
   * 在生成完成后显式刷新详情（双保险，不依赖订阅者是否仍在）。
   *
   * ``rag``：可选的 RAG 接地开关（开启时后端会检索已索引文档并回传引用）。
   */
  start(
    messagesForLLM: Message[],
    conversationId: string,
    rag?: { enabled: boolean; sourceIds?: string[] }
  ): Promise<void> {
    // 锁：同一会话只跑一个。若上次已终态但尚未清理，先清掉再跑。
    if (this.active.has(conversationId)) {
      const g = this.active.get(conversationId)!
      if (g.status === 'running') return Promise.resolve()
      this.clear(conversationId)
    }

    const genId = `chat-${conversationId}-${Date.now()}`
    const state: ActiveGeneration = {
      conversationId,
      genId,
      status: 'running',
      streamingContent: '',
      reasoningSteps: [],
      hadError: false,
    }
    this.active.set(conversationId, state)
    const controller = new AbortController()
    this.controllers.set(conversationId, controller)

    // 登记到全局「异步生成观察器」：切走后 watcher 会在完成时弹提醒
    const lastContent = messagesForLLM[messagesForLLM.length - 1]?.content
    useGenerationStore.getState().registerGeneration({
      id: genId,
      type: 'chat',
      sourcePath: '/chat',
      label: typeof lastContent === 'string' ? lastContent : '[图片对话]',
      target: conversationId,
    })

    return this.run(state, messagesForLLM, controller.signal, rag)
  }

  private async run(
    state: ActiveGeneration,
    messagesForLLM: Message[],
    signal: AbortSignal,
    rag?: { enabled: boolean; sourceIds?: string[] }
  ) {
    const conversationId = state.conversationId
    const toolResults: ToolResult[] = []
    let reasoningRef: ReasoningStep[] = []
    let ragSourcesRef: RagSource[] = []

    const pushReasoning = (step: ReasoningStep) => {
      reasoningRef = [...reasoningRef, step]
      state.reasoningSteps = reasoningRef
      this.notify(conversationId)
    }
    const patchLastTool = (
      patch: Partial<Extract<ReasoningStep, { kind: 'tool' }>>
    ) => {
      const next = [...reasoningRef]
      for (let i = next.length - 1; i >= 0; i--) {
        const step = next[i]
        if (step.kind === 'tool' && step.status === 'running') {
          next[i] = { ...step, ...patch } as ReasoningStep
          break
        }
      }
      reasoningRef = next
      state.reasoningSteps = next
      this.notify(conversationId)
    }
    // 从工具返回 payload 中提取一句可读摘要
    const summarizeResult = (raw: any): string => {
      if (!raw || typeof raw !== 'object') return String(raw ?? '')
      if (raw.error) return String(raw.error)
      if (raw.message) return String(raw.message)
      if (Array.isArray(raw.results) && raw.results.length > 0) {
        return `获取到 ${raw.results.length} 条结果`
      }
      if (raw.success === true) return '执行成功'
      if (raw.success === false) return '执行失败'
      return JSON.stringify(raw).slice(0, 200)
    }

    try {
      await streamChatCompletion(
        messagesForLLM,
        (chunk) => {
          state.streamingContent += chunk
          this.notify(conversationId)
        },
        (tool, params) => {
          // 落定之前的思考文本为一步；若模型未输出任何思考，自动补一条占位说明
          if (state.streamingContent.trim()) {
            pushReasoning({ kind: 'text', content: state.streamingContent.trim() })
            state.streamingContent = ''
          } else if (reasoningRef.length === 0) {
            pushReasoning({ kind: 'text', content: `准备调用「${tool}」获取信息…` })
          }
          pushReasoning({ kind: 'tool', name: tool, params, status: 'running' })
        },
        (result) => {
          toolResults.push(result)
          patchLastTool({
            status: result.success ? 'success' : 'error',
            message: result.message || summarizeResult(result.result),
            success: result.success,
            result: result.result,
          })
          // 工具返回后追加一条中间思考，让过程更连贯
          const summary = result.message || summarizeResult(result.result)
          pushReasoning({
            kind: 'text',
            content: `已收到「${result.tool || '工具'}」结果：${summary}`,
          })
        },
        (error) => {
          state.hadError = true
          state.streamingContent += `\n\n[错误: ${error}]`
          this.notify(conversationId)
        },
        (ctx) => {
          state.contextInfo = ctx
          this.notify(conversationId)
        },
        signal,
        rag,
        (sources) => {
          ragSourcesRef = sources
          state.ragSources = sources
          this.notify(conversationId)
        }
      )

      // 用户主动取消（目前仅 cancel() 触发）→ 不保存半成品
      if (signal.aborted) {
        state.status = 'cancelled'
        useGenerationStore.getState().setStatus(state.genId, 'cancelled')
        this.notify(conversationId)
        this.scheduleClear(conversationId)
        return
      }

      // 流式结束：构建 assistant 消息并落库
      const lastMsg = messagesForLLM[messagesForLLM.length - 1]
      const parentId = lastMsg?.id || null
      if (!parentId) {
        console.error(
          '[chatGenerationManager] lastMsg missing id; conversationId=%s, messagesForLLM.length=%d',
          conversationId,
          messagesForLLM.length
        )
      }
      const assistantMessage: Message = {
        id: generateId(),
        role: 'assistant',
        content: state.streamingContent,
        timestamp: Date.now(),
        parentId,
        metadata: {
          ...(reasoningRef.length > 0 ? { reasoning: reasoningRef } : {}),
          ...(ragSourcesRef.length > 0 ? { ragSources: ragSourcesRef } : {}),
        },
      }
      // 无 metadata 时不传 undefined，保持后端结构干净
      if (!reasoningRef.length && !ragSourcesRef.length) {
        assistantMessage.metadata = undefined
      }
      await addMessageAPI(conversationId, assistantMessage)
      state.finalMessage = assistantMessage
      state.status = state.hadError ? 'failed' : 'completed'
      useGenerationStore.getState().setStatus(state.genId, state.status)
      if (toolResults.some((r) => r.success)) {
        window.dispatchEvent(new CustomEvent('ai-tool-executed'))
      }
      this.notify(conversationId)
      this.scheduleClear(conversationId)
    } catch (e) {
      console.error('chat generation failed', e)
      state.hadError = true
      state.status = 'failed'
      useGenerationStore.getState().setStatus(state.genId, 'failed')
      this.notify(conversationId)
      this.scheduleClear(conversationId)
    }
  }
}

export const chatGenerationManager = new ChatGenerationManager()
