import { apiRequest } from '@/services/api'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { generateId } from '@/utils'
import { useToast } from '@/components/ui/toast'
import { useConfirmDialog } from '@/components/ui/confirm-dialog'
import type { ChatContentPart, Conversation, Message, RagSource, ReasoningStep } from '../types'
import {
  addMessageAPI,
  createConversationAPI,
  deleteConversationAPI,
  fetchConversationDetail,
  fetchConversations,
  switchBranchAPI,
  updateConversationAPI,
} from '../services/chatApi'
import { chatGenerationManager } from '../services/chatGenerationManager'
import type { GenPhase } from '../services/chatGenerationManager'
import { estimateTokensLocal, extractTextFromContent } from '../messageUtils'
import { useAppStore } from '@/stores/appStore'

export function useChatController() {
  const { showToast } = useToast()
  const { showConfirm, ConfirmDialogComponent } = useConfirmDialog()
  const navigate = useNavigate()
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // 跨 Hub 切换时持久化当前会话 ID
  const setAppStoreChatId = useAppStore((state) => state.setChatConversationId)

  // 会话列表（仅从列表 API 获取基本信息）
  const [conversations, setConversations] = useState<Conversation[]>([])

  // 当前会话详情（包含完整消息）
  const [currentConversation, setCurrentConversation] = useState<Conversation | null>(null)

  // 加载状态
  const [isLoading, setIsLoading] = useState(true)

  // 当前会话 ID：本地响应式状态 + 持久化到 AppStore
  const [currentConversationId, setCurrentConversationIdState] = useState<string | null>(null)
  const setCurrentConversationId = useCallback(
    (id: string | null) => {
      setCurrentConversationIdState(id)
      setAppStoreChatId(id)
    },
    [setAppStoreChatId]
  )

  // 详情重载引用（始终指向最新的 loadConversationDetail，供订阅回调使用，避免 effect 重订阅）
  const loadDetailRef = useRef<(id: string) => Promise<void>>(() => Promise.resolve())

  // 始终指向最新 currentConversation 的 ref（persist 回调里读取，避免闭包拿到旧值）
  const currentConvRef = useRef<Conversation | null>(null)
  currentConvRef.current = currentConversation
  // 已同步过 RAG 设置的会话 id（仅在切换会话时重新同步，避免 toggle 自身写回触发循环）
  const lastRagSyncId = useRef<string | null>(null)
  // 当前会话 ID 的 ref（persist effect 读取，避免把 currentConversationId 加入依赖）
  const currentConvIdRef = useRef<string | null>(null)
  currentConvIdRef.current = currentConversationId

  // URL 中的 ?conv=<id>：由「后台完成提醒」的「查看」跳转而来，进入时自动打开对应会话
  const [searchParams, setSearchParams] = useSearchParams()
  useEffect(() => {
    const convId = searchParams.get('conv')
    if (convId && convId !== currentConversationId && conversations.some((c) => c.id === convId)) {
      setCurrentConversationId(convId)
      setSearchParams({}, { replace: true }) // 清除参数，避免反复触发
    }
  }, [searchParams, conversations, currentConversationId, setSearchParams, setCurrentConversationId])

  // 输入内容
  const [input, setInput] = useState('')
  const [pendingImages, setPendingImages] = useState<ChatContentPart[]>([])

  // 是否正在生成回复
  const [isGenerating, setIsGenerating] = useState(false)

  // 生成阶段（retrieving/working/writing）+ 已耗时秒数：解决"长检索无声像卡死"
  const [genPhase, setGenPhase] = useState<GenPhase | null>(null)
  const [genElapsed, setGenElapsed] = useState(0)
  const genStartRef = useRef<number>(0)

  // 生成开始/结束时起停计时器（1s 一跳；unmount/结束即清）
  useEffect(() => {
    if (!isGenerating) {
      setGenElapsed(0)
      return
    }
    genStartRef.current = Date.now()
    setGenElapsed(0)
    const t = setInterval(() => {
      setGenElapsed(Math.floor((Date.now() - genStartRef.current) / 1000))
    }, 1000)
    return () => clearInterval(t)
  }, [isGenerating])

  // 当前流式内容
  const [streamingContent, setStreamingContent] = useState('')

  // 编辑中的会话标题
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')

  // 右键菜单（作为三点按钮的兜底）
  const [contextMenu, setContextMenu] = useState<{
    x: number
    y: number
    conv: Conversation
  } | null>(null)

  // 复制状态
  const [copiedId, setCopiedId] = useState<string | null>(null)

  // 正在内联编辑的消息 ID 与编辑缓冲（用于「编辑最新提问」）
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null)
  const [editBuffer, setEditBuffer] = useState('')

  // 侧边栏折叠（移动端）
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null)

  // 侧边栏可拖拽宽度（桌面端）：持久化到 localStorage，双击手柄复位
  const SIDEBAR_MIN_WIDTH = 220
  const SIDEBAR_DEFAULT_WIDTH = 256
  const SIDEBAR_MAX_WIDTH = 520
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    try {
      const saved = Number(localStorage.getItem('chatSidebarWidth'))
      if (Number.isFinite(saved) && saved >= SIDEBAR_MIN_WIDTH && saved <= SIDEBAR_MAX_WIDTH) {
        return saved
      }
    } catch {
      /* localStorage 不可用时用默认值 */
    }
    return SIDEBAR_DEFAULT_WIDTH
  })
  const [isResizingSidebar, setIsResizingSidebar] = useState(false)
  const resizeSidebarRef = useRef<{ startX: number; startWidth: number } | null>(null)

  // 开始拖拽：监听全局 pointermove / pointerup，宽度 clamp 到 [min, max]
  const startResizeSidebar = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault()
      e.stopPropagation()
      resizeSidebarRef.current = { startX: e.clientX, startWidth: sidebarWidth }
      setIsResizingSidebar(true)
      let lastWidth = sidebarWidth
      const onMove = (ev: PointerEvent) => {
        const st = resizeSidebarRef.current
        if (!st) return
        const delta = ev.clientX - st.startX
        lastWidth = Math.min(
          SIDEBAR_MAX_WIDTH,
          Math.max(SIDEBAR_MIN_WIDTH, st.startWidth + delta)
        )
        setSidebarWidth(lastWidth)
      }
      const onUp = () => {
        resizeSidebarRef.current = null
        setIsResizingSidebar(false)
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', onUp)
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
        try {
          localStorage.setItem('chatSidebarWidth', String(lastWidth))
        } catch {
          /* 忽略持久化失败 */
        }
      }
      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', onUp)
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    },
    [sidebarWidth]
  )

  // 双击手柄：复位到默认宽度
  const resetSidebarWidth = useCallback(() => {
    setSidebarWidth(SIDEBAR_DEFAULT_WIDTH)
    try {
      localStorage.setItem('chatSidebarWidth', String(SIDEBAR_DEFAULT_WIDTH))
    } catch {
      /* 忽略持久化失败 */
    }
  }, [])

  // 上下文窗口用量（后端每轮回传的 context 事件）
  const [contextInfo, setContextInfo] = useState<{
    estimated_tokens: number
    limit: number
    compressed: boolean
  } | null>(null)
  const [ctxExpanded, setCtxExpanded] = useState(false)

  // 思考过程步骤（用于「思考过程」可折叠面板）
  const [reasoningSteps, setReasoningSteps] = useState<ReasoningStep[]>([])
  // 流式思考面板的展开状态（生成中默认展开，用户可手动折叠）
  const [streamPanelOpen, setStreamPanelOpen] = useState(true)

  // 流式生成期间已返回的 RAG 来源（用于实时在正文中渲染引用角标）
  const [streamingRagSources, setStreamingRagSources] = useState<RagSource[]>([])

  // 知识增强（原 RAG 文档检索）：按会话持久化（存 conversation.metadata.rag 兼容旧键，显示为“知识增强”）
  const [ragEnabled, setRagEnabled] = useState(false)
  const [ragSourceIds, setRagSourceIds] = useState<string[]>([])
  const [ragSourcesList, setRagSourcesList] = useState<{ id: string; name: string; kind?: string }[]>([])
  const [ragPickerOpen, setRagPickerOpen] = useState(false)

  // 切换知识增强开关（持久化由 persist effect 自动处理）
  const toggleRag = useCallback((next: boolean) => {
    setRagEnabled(next)
    if (!next) setRagPickerOpen(false)
  }, [])

  // 知识增强开启时拉取当前空间已索引源列表（无论由用户 toggle 还是会话同步触发）
  useEffect(() => {
    if (!ragEnabled) {
      setRagPickerOpen(false)
      return
    }
    apiRequest('/api/rag/sources')
      .then((res) => res.json())
      .then((data) => {
        const list = (data.sources || []).map((s: any) => ({ id: s.id, name: s.name, kind: s.kind || 'local' }))
        setRagSourcesList(list)
        // 迁移旧数据：空数组曾表示“全选”，新逻辑空=零选，自动转为全选显式列表
        if (list.length > 0) {
          setRagSourceIds((prev) => (prev.length === 0 ? list.map((s: any) => s.id) : prev))
        }
      })
      .catch(() => {
        /* 拉取失败不阻断开启 */
      })
  }, [ragEnabled])

  // 来源筛选弹层：点击外部关闭
  useEffect(() => {
    if (!ragPickerOpen) return
    const handle = (e: MouseEvent) => {
      const el = document.getElementById('rag-source-picker')
      if (el && !el.contains(e.target as Node)) setRagPickerOpen(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [ragPickerOpen])

  // 上下文圆环展开：点击外部关闭
  useEffect(() => {
    if (!ctxExpanded) return
    const handle = (e: MouseEvent) => {
      const el = document.getElementById('context-ring')
      if (el && !el.contains(e.target as Node)) setCtxExpanded(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [ctxExpanded])

  // 加载会话列表 — 直达最近且活跃（60min内）的对话，否则停留四宫格（真发送才建库）
  const loadConversations = useCallback(async () => {
    setIsLoading(true)
    try {
      const list = await fetchConversations()
      setConversations(list)
      const ACTIVE_TTL = 60 * 60 * 1000
      const savedId = useAppStore.getState().chatConversationId
      if (savedId && list.some((c) => c.id === savedId)) {
        setCurrentConversationIdState(savedId)
      } else if (savedId) {
        setAppStoreChatId(null)
      }
      // 无选中时，60min内有活跃会话则直达最近一条，否则停留四宫格且收抽屉
      const current = useAppStore.getState().chatConversationId
      if (!current && list.length > 0) {
        const recent = list[0]
        if (Date.now() - (recent.updatedAt || 0) < ACTIVE_TTL) {
          setCurrentConversationIdState(recent.id)
          setDrawerOpen(false)
        } else {
          setDrawerOpen(false)
        }
      } else if (!current && list.length === 0) {
        setDrawerOpen(false)
      }
    } catch (error) {
      console.error('Failed to load conversations:', error)
      showToast('加载对话列表失败', 'error')
    } finally {
      setIsLoading(false)
    }
  }, [setAppStoreChatId, showToast])

  // 加载会话详情
  const loadConversationDetail = useCallback(async (id: string) => {
    try {
      const detail = await fetchConversationDetail(id)
      if (detail) {
        setCurrentConversation(detail)
      }
    } catch (error) {
      console.error('Failed to load conversation detail:', error)
      showToast('加载对话详情失败', 'error')
    }
  }, [showToast])
  loadDetailRef.current = loadConversationDetail

  // 初始加载会话列表
  useEffect(() => {
    void loadConversations()
  }, [loadConversations])

  // 右键菜单：点击外部或 Esc 关闭
  useEffect(() => {
    if (!contextMenu) return
    const handleMouseDown = (e: MouseEvent) => {
      const target = e.target as Node
      const menu = document.getElementById('chat-conv-context-menu')
      if (menu && !menu.contains(target)) {
        setContextMenu(null)
      }
    }
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setContextMenu(null)
    }
    document.addEventListener('mousedown', handleMouseDown)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleMouseDown)
      document.removeEventListener('keydown', handleKey)
    }
  }, [contextMenu])

  // 三点菜单：点击外部关闭
  useEffect(() => {
    if (!activeMenuId) return
    const handle = (e: MouseEvent) => {
      const el = document.getElementById(`conv-menu-${activeMenuId}`)
      if (el && !el.contains(e.target as Node)) setActiveMenuId(null)
    }
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setActiveMenuId(null)
    }
    document.addEventListener('mousedown', handle)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handle)
      document.removeEventListener('keydown', handleKey)
    }
  }, [activeMenuId])

  // 当切换会话时，加载会话详情；并接管该会话可能正在后台跑的生成
  useEffect(() => {
    setEditingMessageId(null)
    setReasoningSteps([])
    setStreamingContent('')
    setStreamingRagSources([])
    setStreamPanelOpen(true)

    if (!currentConversationId) {
      setCurrentConversation(null)
      return
    }

    loadConversationDetail(currentConversationId)

    // 订阅「聊天生成管理器」：生成可能在后台跑（用户切走又切回），
    // 这里把实时流式状态映射到本地 UI；终态时刷新详情并清理。
    let flushing = false
    const sync = async () => {
      const g = chatGenerationManager.getActive(currentConversationId)
      if (!g) {
        setIsGenerating(false)
        setGenPhase(null)
        return
      }
      setIsGenerating(g.status === 'running')
      setGenPhase(g.status === 'running' ? g.phase : null)
      setStreamingContent(g.streamingContent)
      setReasoningSteps(g.reasoningSteps)
      setStreamingRagSources(g.ragSources || [])
      if (g.contextInfo) setContextInfo(g.contextInfo)
      if (g.status !== 'running' && !flushing) {
        // 生成完成/失败/取消：先 await 后端刷新（含分支兄弟信息），
        // 确保 currentConversation 被替换为最新路径后再清掉本地流式残留。
        flushing = true
        try {
          await loadDetailRef.current(currentConversationId)
        } catch (err) {
          console.error('Failed to reload conversation after generation:', err)
        } finally {
          setStreamingContent('')
          setReasoningSteps([])
          setIsGenerating(false)
          setGenPhase(null)
          setStreamPanelOpen(true)
          chatGenerationManager.clear(currentConversationId)
          flushing = false
        }
      }
    }
    const unsub = chatGenerationManager.subscribe(currentConversationId, () => {
      void sync()
    })
    void sync() // 立即接管（若挂载时生成已在跑）
    return unsub
  }, [currentConversationId, loadConversationDetail])

  // 切换会话时，从会话 metadata 恢复 RAG/上下文设置；本地即时估算兜底
  useEffect(() => {
    if (!currentConversation) {
      lastRagSyncId.current = null
      setContextInfo(null)
      return
    }
    const ragMeta = currentConversation.metadata?.rag
    lastRagSyncId.current = currentConversation.id
    setRagEnabled(ragMeta?.enabled ?? false)
    setRagSourceIds(ragMeta?.sourceIds ?? [])
    const ctxMeta = (currentConversation.metadata as any)?.context
    if (ctxMeta?.estimated_tokens) {
      setContextInfo(ctxMeta)
    } else {
      const est = estimateTokensLocal(currentConversation.messages as any)
      if (est > 0) setContextInfo({ estimated_tokens: est, limit: 16000, compressed: false })
      else setContextInfo(null)
    }
  }, [currentConversation])

  // RAG 设置变更时持久化到会话 metadata（跳过同步触发的变更以避免循环）
  useEffect(() => {
    const convId = currentConvIdRef.current
    if (!convId) return
    if (lastRagSyncId.current === convId) {
      // 同步触发的变更，跳过持久化
      lastRagSyncId.current = null
      return
    }
    // 用户操作触发的变更，写回会话 metadata
    const existingMeta = currentConvRef.current?.metadata || {}
    updateConversationAPI(convId, {
      metadata: {
        ...existingMeta,
        rag: { enabled: ragEnabled, sourceIds: ragSourceIds },
      },
    })
  }, [ragEnabled, ragSourceIds])

  // 上下文估算持久化：每次流式 context 事件更新后写回 metadata，绑定对话
  useEffect(() => {
    const convId = currentConvIdRef.current
    if (!convId || !contextInfo) return
    const existingMeta = currentConvRef.current?.metadata || {}
    const prevCtx = (existingMeta as any)?.context
    if (prevCtx?.estimated_tokens === contextInfo.estimated_tokens && prevCtx?.compressed === contextInfo.compressed) return
    updateConversationAPI(convId, {
      metadata: { ...existingMeta, context: contextInfo } as any,
    })
  }, [contextInfo])

  // 自动滚动到底部
  const scrollToBottom = useCallback(() => {
    const root = scrollRef.current
    if (!root) return
    // shadcn ScrollArea 的 ref 指向 Root，真正可滚动的是内部 Viewport
    const viewport = root.querySelector<HTMLDivElement>('[data-radix-scroll-area-viewport]')
    const target = viewport || root
    target.scrollTop = target.scrollHeight
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [currentConversation?.messages, streamingContent, scrollToBottom])

  // 打开对话/切换对话后，确保滚到最新消息
  useEffect(() => {
    scrollToBottom()
  }, [currentConversationId, scrollToBottom])

  // 自动聚焦输入框（四宫格空状态也可直接输入）
  useEffect(() => {
    if (inputRef.current && !isGenerating) {
      inputRef.current.focus()
    }
  }, [currentConversationId, isGenerating])

  // 创建新会话
  const createNewConversation = useCallback(async () => {
    const newConversation: Conversation = {
      id: generateId(),
      title: '新对话',
      messages: [
        {
          id: generateId(),
          role: 'system',
          content: '你是 AI Research OS 的 AI 助手，专门帮助研究人员管理论文、任务、项目和实验。',
          timestamp: Date.now(),
        },
      ],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    }

    // 保存到后端，使用后端返回的真实 conversation（后端可能生成新的 id）
    const created = await createConversationAPI(newConversation)
    if (created) {
      setConversations((prev) => [created, ...prev])
      setCurrentConversationId(created.id)
      setCurrentConversation(created)
      // 知识增强默认开启：同步等待源列表，确保首条消息即带增强（否则四宫格首发无RAG）
      try {
        const res = await apiRequest('/api/rag/sources').then((r) => r.json())
        const sources = res.sources || []
        if (sources.length > 0) {
          const allIds = sources.map((s: any) => s.id)
          setRagEnabled(true)
          setRagSourceIds(allIds)
          const nextMeta = { ...(created.metadata || {}), rag: { enabled: true, sourceIds: allIds } }
          // 同步更新本地与远端，保证 sendMessage 立即可读
          created.metadata = nextMeta as any
          setCurrentConversation({ ...created } as any)
          await updateConversationAPI(created.id, { metadata: nextMeta as any })
        }
      } catch (_e) {
        void _e
      }
      return created
    } else {
      showToast('创建对话失败', 'error')
      return null
    }
  }, [showToast, setCurrentConversationId])

  // 删除会话（二次确认；按钮外层已阻止冒泡，此处无需 event）
  const deleteConversation = useCallback(
    (id: string) => {
      const conv = conversations.find((c) => c.id === id)
      showConfirm({
        title: '删除对话',
        message: `确定要删除 "${conv?.title || '该对话'}" 吗？此操作无法撤销。`,
        variant: 'danger',
        onConfirm: async () => {
          const success = await deleteConversationAPI(id)
          if (success) {
            setConversations((prev) => prev.filter((c) => c.id !== id))
            if (currentConversationId === id) {
              setCurrentConversationId(null)
              setCurrentConversation(null)
            }
            showToast('会话已删除', 'success')
          } else {
            showToast('删除对话失败', 'error')
          }
        },
      })
    },
    [conversations, currentConversationId, showConfirm, showToast, setCurrentConversationId]
  )

  // 开始编辑标题（按钮外层已阻止冒泡，此处无需 event）
  const startEditTitle = useCallback((conv: Conversation) => {
    setEditingId(conv.id)
    setEditTitle(conv.title)
  }, [])

  // 保存标题
  const saveTitle = useCallback(
    async (id: string) => {
      if (editTitle.trim()) {
        const success = await updateConversationAPI(id, { title: editTitle.trim() })
        if (success) {
          setConversations((prev) =>
            prev.map((c) => (c.id === id ? { ...c, title: editTitle.trim() } : c))
          )
          if (currentConversation?.id === id) {
            setCurrentConversation((prev) => prev ? { ...prev, title: editTitle.trim() } : null)
          }
        } else {
          showToast('更新标题失败', 'error')
        }
      }
      setEditingId(null)
    },
    [editTitle, currentConversation?.id, showToast]
  )

  // 核心流式生成（新建 / 重新生成 / 编辑后复用同一逻辑）
  // 生成已解耦到 chatGenerationManager（模块级单例）：组件卸载不再中断，
  // 实时流式状态由订阅回调接管。这里只负责「发起」，无需 await。
  const runGeneration = useCallback(
    (messagesForLLM: Message[]): Promise<void> => {
      if (!currentConversationId) return Promise.resolve()
      const rag = ragEnabled ? { enabled: true, sourceIds: ragSourceIds } : undefined
      return chatGenerationManager.start(messagesForLLM, currentConversationId, rag)
    },
    [currentConversationId, ragEnabled, ragSourceIds]
  )

  // 发送防重入锁：state 异步atch不上同 tick 连击（manager 锁只保生成不保气泡），
  // 用 ref 做同步互斥；发起生成后即放行，由 isGenerating + manager 锁接管后续。
  const sendingRef = useRef(false)

  // 发送消息
  const sendMessage = useCallback(async () => {
    if (sendingRef.current) return
    const text = input.trim()
    if ((!text && pendingImages.length === 0) || isGenerating) return
    sendingRef.current = true
    // 乐观置位：按钮立刻禁用 + 思考提示秒出，不再等首个 SSE 事件
    setIsGenerating(true)

    // 没有当前会话时，在同一次发送动作中创建并继续发送首条消息。
    let targetId = currentConversationId
    let targetConversation = currentConversation
    try {
      if (!targetId) {
        const created = await createNewConversation()
        if (!created) return
        targetId = created.id
        targetConversation = created
      }
      if (!targetConversation || targetConversation.id !== targetId) {
        targetConversation = await fetchConversationDetail(targetId)
        if (!targetConversation) {
          showToast('会话详情尚未加载，请重试', 'error')
          return
        }
      }

      // 构造多模态 content：有图片时组装 [text?, ...image_url]，无图时保持纯文本（向后兼容）
      const content: string | ChatContentPart[] =
        pendingImages.length > 0
          ? [...(text ? [{ type: 'text' as const, text }] : []), ...pendingImages]
          : text

      const userMessage: Message = {
        id: generateId(),
        role: 'user',
        content,
        timestamp: Date.now(),
      }

      // 保存用户消息到后端：失败只警告（15s 超时），照常进入生成；
      // 生成结束落库 assistant 消息，本地气泡不受影响。
      try {
        await addMessageAPI(targetId, userMessage)
      } catch (e) {
        console.error('addMessage failed, continue generation anyway:', e)
        showToast('消息存档失败，仍继续生成（刷新后该条可能缺失）', 'error')
      }

      // 更新本地状态
      const updatedMessages = [...(targetConversation?.messages || []), userMessage]
      setCurrentConversation({ ...targetConversation, messages: updatedMessages })

      // 如果是第一条用户消息，更新标题：fire-and-forget，不阻塞生成启动
      // （历史事故：后端慢时该请求 hang 住整条发送链，表现为气泡已出、输入框没清、生成没开始）。
      const isFirstUserMessage = updatedMessages.filter((m) => m.role === 'user').length === 1
      if (isFirstUserMessage) {
        const titleBase = text || '图片消息'
        const newTitle = titleBase.slice(0, 20) + (titleBase.length > 20 ? '...' : '')
        updateConversationAPI(targetId, { title: newTitle }).then((ok) => {
          if (ok) {
            setConversations((prev) =>
              prev.map((c) => (c.id === targetId ? { ...c, title: newTitle } : c))
            )
          }
        }).catch((e) => console.error('update title failed:', e))
      }

      setInput('')
      setPendingImages([])

      // 复用核心流式生成逻辑；四宫格新建时优先用新建会话的 metadata（已同步全量源），避免首条无增强
      let rag: { enabled: boolean; sourceIds: string[] } | undefined
      const metaRag = (targetConversation as any)?.metadata?.rag
      if (metaRag?.enabled) {
        rag = { enabled: true, sourceIds: metaRag.sourceIds || [] }
      } else if (ragEnabled) {
        rag = { enabled: true, sourceIds: ragSourceIds }
      }
      const startPromise = chatGenerationManager.start(updatedMessages, targetId, rag)
      // 发起即放行 ref（后续由 isGenerating + manager 锁接管），再等待生成结束
      sendingRef.current = false
      await startPromise
    } finally {
      sendingRef.current = false
      // 生成根本没启动起来（start 抛错）才兜底复位；正常生成中由订阅同步保持 true
      const g = chatGenerationManager.getActive(targetId ?? '')
      if (!g || g.status !== 'running') {
        setIsGenerating(false)
        setGenPhase(null)
      }
    }
  }, [input, pendingImages, isGenerating, currentConversationId, currentConversation,
    createNewConversation, ragEnabled, ragSourceIds, showToast])

  // 取消当前生成（发送键在生成中变为 Stop；manager  abort 流并丢弃半成品）
  const handleCancel = useCallback(() => {
    if (currentConversationId) chatGenerationManager.cancel(currentConversationId)
  }, [currentConversationId])

  // 进入/退出某条消息的内联编辑态（仅用于「编辑最新提问」）
  const startEditMessage = useCallback((message: Message) => {
    setEditingMessageId(message.id)
    setEditBuffer(extractTextFromContent(message.content))
  }, [])

  // 重新生成（分叉模式）：创建同级新分支，不删除旧回复
  const regenerate = useCallback(async (messageId: string) => {
    if (isGenerating || !currentConversationId || !currentConversation) return
    const messages = currentConversation.messages
    const idx = messages.findIndex((m) => m.id === messageId)
    if (idx < 0) return
    const target = messages[idx]
    if (target.role !== 'assistant') return

    // 取到该 assistant 之前的所有消息（含触发它的 user 消息）作为 LLM 输入
    const messagesForLLM = messages.slice(0, idx)
    if (messagesForLLM.length === 0) return

    // 本地先移除旧 assistant（后端仍保留为分支）
    setCurrentConversation((prev) => (prev ? { ...prev, messages: messagesForLLM } : null))

    // 生成完成后显式用后端最新路径刷新（双保险：即使订阅者已失效也能替换旧回复）
    await runGeneration(messagesForLLM)
    loadConversationDetail(currentConversationId)
  }, [isGenerating, currentConversationId, currentConversation, runGeneration, loadConversationDetail])

  // 编辑提问（分叉模式）：创建同级新 user 分支 + 重新回答
  const editMessage = useCallback(async (messageId: string, rawContent: string) => {
    if (isGenerating || !currentConversationId || !currentConversation) return
    const trimmedContent = rawContent.trim()
    if (!trimmedContent) return

    const messages = currentConversation.messages
    const idx = messages.findIndex((m) => m.id === messageId)
    if (idx < 0) return
    const target = messages[idx]
    if (target.role !== 'user') return

    // 创建新 user 消息（与原消息同 parent → 兄弟分支）
    const newUserMessage: Message = {
      id: generateId(),
      role: 'user',
      content: trimmedContent,
      timestamp: Date.now(),
      parentId: target.parentId || null,
    }
    await addMessageAPI(currentConversationId, newUserMessage)

    // LLM 输入 = 原消息之前的所有消息 + 新 user 消息
    const messagesForLLM = [...messages.slice(0, idx), newUserMessage]
    setCurrentConversation((prev) => (prev ? { ...prev, messages: messagesForLLM } : null))
    setEditingMessageId(null)

    await runGeneration(messagesForLLM)

    // 生成完成后显式用后端最新路径刷新（双保险：即使订阅者已失效也能替换旧回复）
    loadConversationDetail(currentConversationId)
  }, [isGenerating, currentConversationId, currentConversation, runGeneration, loadConversationDetail])

  // 切换分支：导航到同一 parent 下的不同兄弟
  const switchBranch = useCallback(async (targetMessageId: string) => {
    if (!currentConversationId || isGenerating) return
    const updated = await switchBranchAPI(currentConversationId, targetMessageId)
    if (updated) {
      setCurrentConversation(updated)
    }
  }, [currentConversationId, isGenerating])

  // 处理键盘事件
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        sendMessage()
      }
    },
    [sendMessage]
  )

  // 选择图片 -> 读取为 base64 data URI，作为多模态 content 暂存
  const handleImageSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    Array.from(files).forEach((file) => {
      if (!file.type.startsWith('image/')) return
      const reader = new FileReader()
      reader.onload = () => {
        const url = reader.result as string
        setPendingImages((prev) => [...prev, { type: 'image_url', image_url: { url } }])
      }
      reader.readAsDataURL(file)
    })
    e.target.value = ''  // 允许重复选择同一文件
  }, [])

  // 移除已选图片
  const removeImage = useCallback((idx: number) => {
    setPendingImages((prev) => prev.filter((_, i) => i !== idx))
  }, [])

  // 复制消息内容
  const copyMessage = useCallback(
    async (content: string, id: string) => {
      try {
        await navigator.clipboard.writeText(content)
        setCopiedId(id)
        setTimeout(() => setCopiedId(null), 2000)
      } catch {
        showToast('复制失败', 'error')
      }
    },
    [showToast]
  )

  // 派生：当前对话最新分支点的版本提示（用于顶部栏显示"第 X / N 个版本"）
  const branchTip = useMemo(() => {
    const msgs = currentConversation?.messages || []
    // 从后往前找第一条有兄弟的消息，作为"最新分支点"
    for (let i = msgs.length - 1; i >= 0; i--) {
      const m = msgs[i]
      if ((m.siblingCount ?? 1) > 1) {
        return {
          index: (m.siblingIndex ?? 0) + 1,
          count: m.siblingCount ?? 1,
          role: m.role,
        }
      }
    }
    return null
  }, [currentConversation?.messages])

  return {
    showConfirm, ConfirmDialogComponent, conversations, currentConversation, isLoading,
    currentConversationId, setCurrentConversationId, input, setInput, pendingImages,
    isGenerating, genPhase, genElapsed, streamingContent, editingId, setEditingId,
    editTitle, setEditTitle, contextMenu, setContextMenu, copiedId, editingMessageId,
    setEditingMessageId, editBuffer, setEditBuffer, sidebarCollapsed, setSidebarCollapsed,
    drawerOpen, setDrawerOpen, activeMenuId, setActiveMenuId, sidebarWidth,
    isResizingSidebar, startResizeSidebar, resetSidebarWidth, contextInfo, ctxExpanded,
    setCtxExpanded, reasoningSteps, streamPanelOpen, setStreamPanelOpen,
    streamingRagSources, ragEnabled, ragSourceIds, setRagSourceIds, ragSourcesList,
    ragPickerOpen, setRagPickerOpen, scrollRef, inputRef, toggleRag,
    createNewConversation, deleteConversation, startEditTitle, saveTitle, sendMessage,
    handleCancel, startEditMessage, regenerate, editMessage, switchBranch,
    handleKeyDown, handleImageSelect, removeImage, copyMessage, branchTip, navigate
  }
}
