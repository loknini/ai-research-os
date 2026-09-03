import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn, generateId, sanitizeToolCallTrace } from '@/utils'
import { useToast } from '@/components/ui/toast'
import { useConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  MessageSquare,
  Plus,
  Trash2,
  Edit3,
  Send,
  Bot,
  User,
  Loader2,
  ChevronLeft,
  ChevronRight,
  Copy,
  Check,
  Sparkles,
  RefreshCw,
  X,
  Wrench,
  BookOpen,
  ChevronDown,
  Image,
} from 'lucide-react'
import { Conversation, Message, ReasoningStep, RagSource, ChatContentPart } from './types'
import {
  fetchConversations,
  fetchConversationDetail,
  createConversationAPI,
  updateConversationAPI,
  deleteConversationAPI,
  addMessageAPI,
  switchBranchAPI,
} from './services/chatApi'
import { chatGenerationManager } from './services/chatGenerationManager'
import MessageContent from './components/MessageContent'
import { useAppStore } from '@/stores/appStore'

// 本地 token 估算（与 backend/server/context.py:28 同款 CJK=1 / 其它非空=0.25）
function estimateTokensLocal(messages: any[]): number {
  let total = 0
  for (const m of messages || []) {
    const c = typeof m.content === 'string' ? m.content : JSON.stringify(m.content || '')
    for (const ch of c) {
      if (ch >= '一' && ch <= '鿿' || ch >= '぀' && ch <= 'ヿ' || ch >= '가' && ch <= '힯') total += 1
      else if (!/\s/.test(ch)) total += 0.25
    }
  }
  return Math.floor(total)
}

// 从多模态 content（str 或 parts[]）提取纯文本，用于标题 / 编辑 / 复制等场景。
function extractTextFromContent(content: string | ChatContentPart[]): string {
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content
      .map((p) => (p.type === 'text' ? p.text || '' : '[图片]'))
      .join('\n')
      .trim()
  }
  return ''
}

// 思考过程可折叠面板：列出模型中间思考文本与工具调用（参数 + 结果）。
// 生成期间默认展开（open 由外部受控），已保存消息默认折叠（uncontrolled）。
function ReasoningPanel({
  steps,
  open,
  onToggle,
}: {
  steps: ReasoningStep[]
  open?: boolean
  onToggle?: () => void
}) {
  const toolCount = steps.filter((s) => s.kind === 'tool').length
  const isControlled = open !== undefined && onToggle !== undefined
  return (
    <details
      open={open}
      className="group rounded-xl border border-border/60 bg-muted/40 overflow-hidden"
    >
      <summary
        onClick={
          isControlled
            ? (e) => {
                e.preventDefault()
                onToggle?.()
              }
            : undefined
        }
        className="flex items-center gap-2 px-3 py-2 cursor-pointer text-xs text-muted-foreground select-none hover:bg-muted/60 list-none [&::-webkit-details-marker]:hidden"
      >
        <ChevronRight className="w-3.5 h-3.5 transition-transform group-open:rotate-90" />
        <span>思考过程</span>
        {toolCount > 0 && (
          <span className="rounded-full bg-primary/10 text-primary px-1.5 py-0.5 text-[10px] font-medium">
            调用 {toolCount} 个工具
          </span>
        )}
      </summary>
      <div className="px-3 pb-3 space-y-2">
        {steps.map((s, i) =>
          s.kind === 'text' ? (
            <p
              key={i}
              className="text-xs text-muted-foreground/90 leading-relaxed whitespace-pre-wrap border-l-2 border-border pl-2"
            >
              {s.content}
            </p>
          ) : (
            <div
              key={i}
              className="rounded-lg bg-background/60 px-2.5 py-2 border border-border/50"
            >
              <div className="flex items-center gap-1.5 text-xs">
                {s.status === 'running' ? (
                  <Loader2 className="w-3 h-3 animate-spin text-primary" />
                ) : s.status === 'success' ? (
                  <Check className="w-3 h-3 text-green-600" />
                ) : (
                  <X className="w-3 h-3 text-red-600" />
                )}
                <span className="font-medium">{s.name}</span>
                <span className="text-[10px] text-muted-foreground">
                  {s.status === 'running'
                    ? '执行中'
                    : s.status === 'success'
                      ? '成功'
                      : '失败'}
                </span>
              </div>
              {s.params && Object.keys(s.params).length > 0 && (
                <details className="mt-1">
                  <summary className="text-[10px] text-muted-foreground/80 cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden hover:text-muted-foreground">
                    参数
                  </summary>
                  <pre className="mt-1 text-[10px] text-muted-foreground bg-muted/50 rounded p-1.5 overflow-x-auto whitespace-pre-wrap break-all">
                    {JSON.stringify(s.params, null, 2)}
                  </pre>
                </details>
              )}
              {s.message && (
                <p
                  className={cn(
                    'mt-1 text-[10px] leading-relaxed',
                    s.status === 'error' ? 'text-red-600' : 'text-muted-foreground'
                  )}
                >
                  {s.message}
                </p>
              )}
              {s.result !== undefined && s.status !== 'running' && (
                <details className="mt-1">
                  <summary className="text-[10px] text-muted-foreground/80 cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden hover:text-muted-foreground">
                    完整返回结果
                  </summary>
                  <pre className="mt-1 text-[10px] text-muted-foreground bg-muted/50 rounded p-1.5 overflow-x-auto whitespace-pre-wrap break-all max-h-40">
                    {JSON.stringify(s.result, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          )
        )}
      </div>
    </details>
  )
}

// RAG 引用溯源卡片：列出回答所依据的文档片段，可展开查看原文。
// openRank 受控，方便正文中的引用角标点击后联动展开。
function RagCitations({
  sources,
  openRank,
  onOpenRank,
}: {
  sources: RagSource[]
  openRank: number | null
  onOpenRank: (rank: number | null) => void
}) {
  if (!sources.length) return null
  return (
    <div id="rag-citations" className="mt-3 rounded-xl border border-border/60 bg-muted/30 p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-2">
        <BookOpen className="w-3.5 h-3.5" />
        <span>引用来源（{sources.length}）</span>
        <span className="text-[10px] text-muted-foreground/70">点击角标或卡片展开片段</span>
      </div>
      <div className="space-y-1.5">
        {sources.map((s) => {
          const open = openRank === s.rank
          const pageLabel =
            s.pageEnd && s.pageEnd !== s.pageStart
              ? `第 ${s.pageStart}-${s.pageEnd} 页`
              : `第 ${s.pageStart} 页`
          return (
            <button
              key={s.rank}
              id={`rag-cite-${s.rank}`}
              onClick={() => onOpenRank(open ? null : s.rank)}
              className={cn(
                'w-full text-left rounded-lg bg-background/60 border px-2.5 py-2 transition-colors',
                open ? 'border-primary/40 bg-primary/5' : 'border-border/50 hover:bg-background'
              )}
            >
              <div className="flex items-center gap-2 text-xs">
                <span className="inline-flex h-4 w-4 items-center justify-center rounded bg-primary/15 text-primary text-[10px] font-semibold flex-shrink-0">
                  {s.rank}
                </span>
                <span className="font-medium truncate flex-1">{s.fileName}</span>
                <span className="text-[10px] text-muted-foreground whitespace-nowrap flex-shrink-0">
                  {pageLabel}
                </span>
              </div>
              {open && (
                <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground whitespace-pre-wrap border-l-2 border-border pl-2 max-h-44 overflow-auto">
                  {s.snippet}
                </p>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// 助手消息正文：把模型可能误写入正文的 <tool_call> 等内部工具调用标记
// 折叠进「调试」区；同时把 [n] 渲染为可点击的 RAG 引用角标。
function AssistantContent({
  content,
  sources,
  onCitationClick,
}: {
  content: string | ChatContentPart[]
  sources?: RagSource[]
  onCitationClick?: (rank: number) => void
}) {
  const text = typeof content === 'string' ? content : extractTextFromContent(content)
  const { clean, trace } = useMemo(() => sanitizeToolCallTrace(text), [text])
  return (
    <>
      <MessageContent
        content={clean}
        citationSources={sources}
        onCitationClick={onCitationClick}
      />
      {trace && (
        <details className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/5 overflow-hidden">
          <summary className="flex items-center gap-1.5 px-3 py-2 cursor-pointer text-xs text-amber-700 select-none list-none [&::-webkit-details-marker]:hidden">
            <Wrench className="w-3.5 h-3.5" />
            模型原始工具调用痕迹（调试）
            <span className="text-[10px] text-amber-600/70">点击展开</span>
          </summary>
          <pre className="px-3 pb-3 text-[11px] text-muted-foreground whitespace-pre-wrap break-all max-h-60 overflow-auto">
            {trace}
          </pre>
        </details>
      )}
    </>
  )
}

// 单条助手消息的完整渲染：思考过程 + 正文（含引用角标）+ 引用来源卡片。
// 把「正文角标点击」与「来源卡片展开」联动，并自动滚动到对应卡片。
function AssistantMessageBody({
  content,
  reasoning,
  sources,
}: {
  content: string | ChatContentPart[]
  reasoning?: ReasoningStep[]
  sources?: RagSource[]
}) {
  const [openRank, setOpenRank] = useState<number | null>(null)
  const handleCitationClick = useCallback((rank: number) => {
    setOpenRank((prev) => (prev === rank ? null : rank))
    // 延迟滚动，等 DOM 展开后再定位
    setTimeout(() => {
      const el = document.getElementById(`rag-cite-${rank}`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }, 60)
  }, [])
  return (
    <>
      {reasoning && reasoning.length > 0 && <ReasoningPanel steps={reasoning} />}
      <AssistantContent
        content={content}
        sources={sources}
        onCitationClick={sources?.length ? handleCitationClick : undefined}
      />
      {sources && sources.length > 0 && (
        <RagCitations sources={sources} openRank={openRank} onOpenRank={setOpenRank} />
      )}
    </>
  )
}

export default function ChatHub() {
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

  // 思考过程步骤（用于「思考过程」可折叠面板）
  const [reasoningSteps, setReasoningSteps] = useState<ReasoningStep[]>([])
  // 流式思考面板的展开状态（生成中默认展开，用户可手动折叠）
  const [streamPanelOpen, setStreamPanelOpen] = useState(true)

  // 流式生成期间已返回的 RAG 来源（用于实时在正文中渲染引用角标）
  const [streamingRagSources, setStreamingRagSources] = useState<RagSource[]>([])

  // 知识增强（原 RAG 文档检索）：按会话持久化（存 conversation.metadata.rag 兼容旧键，显示为“知识增强”）
  const [ragEnabled, setRagEnabled] = useState(false)
  const [ragSourceIds, setRagSourceIds] = useState<string[]>([])
  const [ragSourcesList, setRagSourcesList] = useState<{ id: string; name: string }[]>([])
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
    fetch('/api/rag/sources')
      .then((res) => res.json())
      .then((data) => {
        const list = (data.sources || []).map((s: any) => ({ id: s.id, name: s.name }))
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

  // 加载会话列表
  const loadConversations = useCallback(async () => {
    setIsLoading(true)
    try {
      const list = await fetchConversations()
      setConversations(list)
      const savedId = useAppStore.getState().chatConversationId
      if (savedId && list.some((c) => c.id === savedId)) {
        setCurrentConversationIdState(savedId)
      } else if (savedId) {
        setAppStoreChatId(null)
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
        return
      }
      setIsGenerating(g.status === 'running')
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

  // 自动聚焦输入框
  useEffect(() => {
    if (currentConversationId && inputRef.current) {
      inputRef.current.focus()
    }
  }, [currentConversationId])

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
      // 知识增强默认开启：若当前空间已有索引源，自动开启（否则保持关闭避免空提示）
      fetch('/api/rag/sources')
        .then((r) => r.json())
        .then((data) => {
          const hasSources = (data.sources || []).length > 0
          if (hasSources) {
            setRagEnabled(true)
            // 持久化到新会话 metadata（兼容旧 rag 键）
            updateConversationAPI(created.id, { metadata: { ...(created.metadata || {}), rag: { enabled: true, sourceIds: [] } } })
          }
        })
        .catch(() => {})
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

  // 发送消息
  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if ((!text && pendingImages.length === 0) || isGenerating) return

    // 没有当前会话时，在同一次发送动作中创建并继续发送首条消息。
    let targetId = currentConversationId
    let targetConversation = currentConversation
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

    // 保存用户消息到后端
    await addMessageAPI(targetId, userMessage)

    // 更新本地状态
    const updatedMessages = [...(targetConversation?.messages || []), userMessage]
    setCurrentConversation({ ...targetConversation, messages: updatedMessages })

    // 如果是第一条用户消息，更新标题
    const isFirstUserMessage = updatedMessages.filter((m) => m.role === 'user').length === 1
    if (isFirstUserMessage) {
      const titleBase = text || '图片消息'
      const newTitle = titleBase.slice(0, 20) + (titleBase.length > 20 ? '...' : '')
      await updateConversationAPI(targetId, { title: newTitle })
      setConversations((prev) =>
        prev.map((c) => (c.id === targetId ? { ...c, title: newTitle } : c))
      )
    }

    setInput('')
    setPendingImages([])

    // 复用核心流式生成逻辑
    const rag = ragEnabled ? { enabled: true, sourceIds: ragSourceIds } : undefined
    await chatGenerationManager.start(updatedMessages, targetId, rag)
  }, [input, pendingImages, isGenerating, currentConversationId, currentConversation,
    createNewConversation, ragEnabled, ragSourceIds, showToast])

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

  // 清空当前会话（删除并创建新会话）
  const clearCurrentConversation = useCallback(async () => {
    if (!currentConversationId) return
    
    const oldId = currentConversationId
    const title = currentConversation?.title || '新对话'
    
    // 删除旧会话
    await deleteConversationAPI(oldId)
    
    // 创建新会话
    const newConversation: Conversation = {
      id: generateId(),
      title,
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
    
    await createConversationAPI(newConversation)
    
    // 更新本地状态
    setConversations((prev) => [newConversation, ...prev.filter(c => c.id !== oldId)])
    setCurrentConversationId(newConversation.id)
    setCurrentConversation(newConversation)
    showToast('会话已清空', 'success')
  }, [currentConversationId, currentConversation?.title, showToast, setCurrentConversationId])

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

  return (
    <div className="flex h-full bg-background">
      {/* 左侧会话列表（宽度可拖拽调整） */}
      <div
        className={cn(
          'relative border-r bg-card flex flex-col flex-shrink-0',
          !isResizingSidebar && 'transition-all duration-300',
          sidebarCollapsed && 'w-0 overflow-hidden border-r-0'
        )}
        style={sidebarCollapsed ? undefined : { width: sidebarWidth }}
      >
        {/* 拖拽调宽手柄：右缘竖条，双击复位 */}
        {!sidebarCollapsed && (
          <div
            onPointerDown={startResizeSidebar}
            onDoubleClick={resetSidebarWidth}
            role="separator"
            aria-orientation="vertical"
            aria-label="拖拽调整会话列表宽度（双击复位）"
            className="absolute right-0 top-0 h-full w-1.5 cursor-col-resize z-20 group/resizer"
            style={{ touchAction: 'none' }}
          >
            <div className="absolute right-0 top-0 h-full w-[3px] bg-transparent group-hover/resizer:bg-primary/40 group-active/resizer:bg-primary/70 transition-colors" />
          </div>
        )}
        {/* 新建会话按钮 */}
        <div className="p-4 border-b">
          <Button
            onClick={createNewConversation}
            className="w-full justify-start gap-2"
            variant="outline"
          >
            <Plus className="w-4 h-4" />
            新建对话
          </Button>
        </div>

        {/* 会话列表 */}
        {/* Radix ScrollArea 的 viewport 内层是 display:table，会被内容天然宽度撑破容器
            （对话条 343px > 侧边栏宽度的根因），这里强制改回 block 让 w-full/min-w-0 生效 */}
        <ScrollArea className="flex-1 [&_[data-radix-scroll-area-viewport]>div]:!block">
          <div className="p-2 space-y-1">
            {conversations.map((conv) => (
              <div
                key={conv.id}
                onClick={() => setCurrentConversationId(conv.id)}
                onContextMenu={(e) => {
                  e.preventDefault()
                  setContextMenu({ x: e.clientX, y: e.clientY, conv })
                }}
                className={cn(
                  'group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors min-w-0 w-full',
                  currentConversationId === conv.id
                    ? 'bg-primary text-primary-foreground'
                    : 'hover:bg-accent'
                )}
              >
                <MessageSquare className="w-4 h-4 flex-shrink-0" />
                <div className="flex-1 min-w-0 overflow-hidden">
                  {editingId === conv.id ? (
                    <Input
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onBlur={() => saveTitle(conv.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') saveTitle(conv.id)
                        if (e.key === 'Escape') setEditingId(null)
                      }}
                      onClick={(e) => e.stopPropagation()}
                      className={cn(
                        'h-7 text-sm py-0 px-2 w-full shadow-sm',
                        currentConversationId === conv.id
                          ? 'bg-primary-foreground text-primary border-primary-foreground/50 focus-visible:ring-2 focus-visible:ring-primary-foreground/70 focus-visible:border-primary-foreground'
                          : 'bg-background border-input focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-ring'
                      )}
                      autoFocus
                    />
                  ) : (
                    <p className="text-sm truncate">
                      {conv.title}
                    </p>
                  )}
                </div>
                {editingId !== conv.id && (
                  <div
                    className="flex-shrink-0 flex items-center gap-0.5 p-0.5 rounded-lg bg-muted/80 border border-border/60 shadow-sm"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      onClick={() => startEditTitle(conv)}
                      className={cn(
                        'p-1.5 rounded-md transition-colors',
                        currentConversationId === conv.id
                          ? 'bg-primary/10 text-primary-foreground hover:bg-primary/20'
                          : 'bg-background text-foreground hover:bg-accent'
                      )}
                      aria-label={`重命名 "${conv.title}"`}
                    >
                      <Edit3 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => deleteConversation(conv.id)}
                      className={cn(
                        'p-1.5 rounded-md transition-colors',
                        currentConversationId === conv.id
                          ? 'bg-primary/10 text-destructive-foreground hover:bg-red-500/30'
                          : 'bg-background text-destructive hover:bg-destructive/10'
                      )}
                      aria-label={`删除 "${conv.title}"`}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </div>
            ))}
            {isLoading && (
              <div className="text-center text-muted-foreground py-8">
                <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2" />
                <p className="text-sm">加载中...</p>
              </div>
            )}
            {!isLoading && conversations.length === 0 && (
              <div className="text-center text-muted-foreground py-8">
                <p className="text-sm">暂无对话</p>
                <p className="text-xs mt-1">点击上方按钮创建</p>
              </div>
            )}
          </div>
        </ScrollArea>

        {/* 底部信息 */}
        <div className="p-4 border-t text-xs text-muted-foreground">
          <p>AI Research OS 助手</p>
          <p className="mt-1">基于 FastAPI LLM 后端</p>
        </div>
      </div>

      {/* 右键菜单兜底 */}
      {contextMenu && (
        <div
          id="chat-conv-context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          className="fixed z-[100] min-w-[160px] rounded-lg border border-border/60 bg-popover text-popover-foreground shadow-lg overflow-hidden py-1"
        >
          <button
            onClick={() => {
              startEditTitle(contextMenu.conv)
              setContextMenu(null)
            }}
            className="w-full px-3 py-2 text-sm flex items-center gap-2 transition-colors text-left text-foreground hover:bg-accent focus-visible:bg-accent"
          >
            <Edit3 className="w-3.5 h-3.5 flex-shrink-0" />
            <span>重命名</span>
          </button>
          <button
            onClick={() => {
              deleteConversation(contextMenu.conv.id)
              setContextMenu(null)
            }}
            className="w-full px-3 py-2 text-sm flex items-center gap-2 transition-colors text-left text-destructive hover:bg-destructive/10 focus-visible:bg-destructive/10"
          >
            <Trash2 className="w-3.5 h-3.5 flex-shrink-0" />
            <span>删除</span>
          </button>
        </div>
      )}

      {/* 右侧聊天区域 */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* 顶部栏 */}
        <div className="h-14 border-b flex items-center justify-between px-4">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              className="lg:hidden"
            >
              <ChevronLeft
                className={cn('w-4 h-4 transition-transform', sidebarCollapsed && 'rotate-180')}
              />
            </Button>
            <h2 className="font-semibold">
              {currentConversation?.title || 'AI 助手'}
            </h2>
            {branchTip && (
              <span
                className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
                title={`当前显示该${branchTip.role === 'user' ? '提问' : '回复'}的第 ${branchTip.index}/${branchTip.count} 个版本`}
              >
                版本 {branchTip.index}/{branchTip.count}
              </span>
            )}
          </div>
          {currentConversation && (
            <div className="flex items-center gap-2">
              {/* 知识增强开关 + 来源筛选 */}
              <div className="flex items-center gap-1.5">
                <Button
                  variant={ragEnabled ? 'default' : 'ghost'}
                  size="sm"
                  onClick={() => toggleRag(!ragEnabled)}
                  title="启用知识增强（RAG）：基于已索引文档回答并标注引用出处"
                >
                  <BookOpen className="w-4 h-4 mr-1" />
                  {ragEnabled ? '知识增强·开' : '知识增强'}
                </Button>
                {ragEnabled && (
                  <div className="relative" id="rag-source-picker-anchor">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setRagPickerOpen((v) => !v)}
                      title="选择要检索的文档源（默认全部）"
                    >
                      来源 {ragSourceIds.length === ragSourcesList.length && ragSourcesList.length > 0 ? '全部' : `${ragSourceIds.length}/${ragSourcesList.length || 0}`}
                      <ChevronDown className="w-3.5 h-3.5 ml-1" />
                    </Button>
                    {ragPickerOpen && (
                      <div
                        id="rag-source-picker"
                        className="absolute right-0 top-full mt-1 z-30 w-64 rounded-lg border border-border/60 bg-popover text-popover-foreground shadow-lg p-2 max-h-72 overflow-auto"
                      >
                        {ragSourcesList.length === 0 ? (
                          <p className="text-xs text-muted-foreground px-1 py-2">
                            暂无已索引文档
                          </p>
                        ) : (
                          <>
                            <label className="flex items-center gap-2 px-1.5 py-1.5 rounded hover:bg-accent cursor-pointer text-sm font-medium border-b border-border/40 mb-1">
                              <input
                                type="checkbox"
                                checked={ragSourceIds.length === ragSourcesList.length && ragSourcesList.length > 0}
                                ref={(el) => {
                                  if (el) el.indeterminate = ragSourceIds.length > 0 && ragSourceIds.length < ragSourcesList.length
                                }}
                                onChange={() => {
                                  if (ragSourceIds.length === ragSourcesList.length) setRagSourceIds([])
                                  else setRagSourceIds(ragSourcesList.map((s) => s.id))
                                }}
                              />
                              <span>全部来源 {ragSourceIds.length === ragSourcesList.length ? '(已选全部)' : ` (已选 ${ragSourceIds.length}/${ragSourcesList.length})`}</span>
                            </label>
                            {ragSourcesList.map((s) => {
                              const checked = ragSourceIds.includes(s.id)
                              return (
                                <label
                                  key={s.id}
                                  className="flex items-center gap-2 px-1.5 py-1.5 rounded hover:bg-accent cursor-pointer text-sm"
                                >
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => {
                                      setRagSourceIds((prev) => (checked ? prev.filter((id) => id !== s.id) : [...prev, s.id]))
                                    }}
                                  />
                                  <span className="truncate">{s.name}</span>
                                </label>
                              )
                            })}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={clearCurrentConversation}
                disabled={currentConversation.messages.length <= 1}
              >
                <Trash2 className="w-4 h-4 mr-1" />
                清空
              </Button>
            </div>
          )}
        </div>

        {/* 知识增强已开启但无已索引源时的提示条 */}
        {ragEnabled && ragSourcesList.length === 0 && (
          <div className="flex items-center gap-2 px-4 py-2 bg-amber-500/5 border-b border-amber-500/20 text-sm">
            <BookOpen className="w-4 h-4 text-amber-600 flex-shrink-0" />
            <span className="text-amber-700">
              当前空间还没有已索引的文档，知识增强将无法生效。
            </span>
            <button
              onClick={() => navigate('/settings#rag')}
              className="text-amber-600 hover:text-amber-700 underline underline-offset-2 font-medium ml-1"
            >
              前往设置建立索引 →
            </button>
          </div>
        )}

        {/* 消息列表 */}
        <ScrollArea ref={scrollRef} className="flex-1">
          {!currentConversation ? (
            // 空状态
            <div className="h-full flex flex-col items-center justify-center p-8">
              <div className="w-20 h-20 rounded-2xl bg-primary/10 flex items-center justify-center mb-6">
                <Sparkles className="w-10 h-10 text-primary" />
              </div>
              <h2 className="text-2xl font-bold mb-2">AI 研究助手</h2>
              <p className="text-muted-foreground text-center max-w-md mb-8">
                我可以帮助您管理论文、任务、项目和实验。开始一个新的对话，或从左侧选择一个历史会话。
              </p>
              <div className="grid grid-cols-2 gap-4 max-w-lg w-full">
                {[
                  { icon: '📄', title: '论文管理', desc: '抓取、总结论文' },
                  { icon: '✅', title: '任务跟踪', desc: '创建和管理任务' },
                  { icon: '💻', title: '代码辅助', desc: '生成和优化代码' },
                  { icon: '🔬', title: '实验追踪', desc: '同步 SwanLab 数据' },
                ].map((item) => (
                  <button
                    key={item.title}
                    onClick={() => {
                      createNewConversation()
                      setInput(`帮我${item.desc}`)
                    }}
                    className="p-4 rounded-xl border hover:border-primary hover:bg-primary/5 transition-colors text-left"
                  >
                    <span className="text-2xl mb-2 block">{item.icon}</span>
                    <p className="font-medium">{item.title}</p>
                    <p className="text-sm text-muted-foreground">{item.desc}</p>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto py-6 space-y-6">
              {currentConversation.messages
                .filter((m) => m.role !== 'system')
                .map((message) => (
                  <div
                    key={message.id}
                    className={cn(
                      'flex gap-4 px-4',
                      message.role === 'user' ? 'flex-row-reverse' : ''
                    )}
                  >
                    {/* 头像 */}
                    <div
                      className={cn(
                        'w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0',
                        message.role === 'user' ? 'bg-primary' : 'bg-muted'
                      )}
                    >
                      {message.role === 'user' ? (
                        <User className="w-4 h-4 text-primary-foreground" />
                      ) : (
                        <Bot className="w-4 h-4" />
                      )}
                    </div>

                    {/* 消息内容 */}
                    <div className="flex-1 space-y-2">
                      <div
                        className={cn(
                          'rounded-2xl px-4 py-3',
                          message.role === 'user'
                            ? 'bg-primary text-primary-foreground ml-auto max-w-[85%]'
                            : 'bg-muted max-w-full'
                        )}
                      >
                        {message.role === 'user' ? (
                          editingMessageId === message.id ? (
                            <div className="space-y-2">
                              <textarea
                                value={editBuffer}
                                onChange={(e) => setEditBuffer(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                                    editMessage(message.id, editBuffer)
                                  }
                                  if (e.key === 'Escape') setEditingMessageId(null)
                                }}
                                rows={3}
                                autoFocus
                                className="w-full resize-none rounded-lg bg-background/80 px-3 py-2 text-sm text-foreground outline-none ring-1 ring-border focus:ring-primary/40"
                              />
                              <div className="flex items-center gap-2">
                                <Button
                                  size="sm"
                                  className="h-7 px-3"
                                  disabled={!editBuffer.trim()}
                                  onClick={() => editMessage(message.id, editBuffer)}
                                >
                                  保存并重答
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 px-3"
                                  onClick={() => setEditingMessageId(null)}
                                >
                                  取消
                                </Button>
                              </div>
                            </div>
                          ) : Array.isArray(message.content) ? (
                            <div className="space-y-2">
                              {message.content.map((part, i) =>
                                part.type === 'image_url' ? (
                                  <img
                                    key={i}
                                    src={part.image_url?.url}
                                    alt="用户上传图片"
                                    className="max-w-xs rounded-lg border border-border"
                                  />
                                ) : part.text ? (
                                  <p key={i} className="whitespace-pre-wrap">{part.text}</p>
                                ) : null
                              )}
                            </div>
                          ) : (
                            <p className="whitespace-pre-wrap">{message.content}</p>
                          )
                        ) : (
                          <div className="prose prose-sm dark:prose-invert max-w-none space-y-2">
                            <AssistantMessageBody
                              content={message.content}
                              reasoning={message.metadata?.reasoning}
                              sources={message.metadata?.ragSources}
                            />
                          </div>
                        )}
                      </div>

                      {/* 分支导航 + 操作按钮 */}
                      <div className={cn(
                        'flex items-center gap-1',
                        message.role === 'user' ? 'justify-end' : 'justify-start'
                      )}>
                        {/* 分支导航：< N/M > —— 有兄弟版本时始终可见 */}
                        {(message.siblingCount ?? 1) > 1 && (
                          <div
                            className="inline-flex items-center gap-0.5 rounded-full border border-border/60 bg-background px-2 py-0.5 text-xs text-foreground shadow-sm"
                            title="该消息存在多个版本，可点击箭头切换"
                          >
                            <button
                              className="p-0.5 rounded hover:bg-accent disabled:opacity-30 disabled:cursor-not-allowed"
                              disabled={(message.siblingIndex ?? 0) === 0 || isGenerating}
                              onClick={() => {
                                const sibs = message.siblingIds ?? []
                                const cur = message.siblingIndex ?? 0
                                if (cur > 0 && sibs[cur - 1]) {
                                  switchBranch(sibs[cur - 1])
                                }
                              }}
                            >
                              <ChevronLeft className="w-3.5 h-3.5" />
                            </button>
                            <span className="tabular-nums px-0.5 min-w-[2.5ch] text-center">
                              {(message.siblingIndex ?? 0) + 1}/{message.siblingCount}
                            </span>
                            <button
                              className="p-0.5 rounded hover:bg-accent disabled:opacity-30 disabled:cursor-not-allowed"
                              disabled={(message.siblingIndex ?? 0) >= (message.siblingCount ?? 1) - 1 || isGenerating}
                              onClick={() => {
                                const sibs = message.siblingIds ?? []
                                const cur = message.siblingIndex ?? 0
                                if (cur < sibs.length - 1 && sibs[cur + 1]) {
                                  switchBranch(sibs[cur + 1])
                                }
                              }}
                            >
                              <ChevronRight className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        )}
                        {/* 编辑 / 重新回答 / 复制 —— hover 才出现 */}
                        <div className="flex items-center gap-1 opacity-0 hover:opacity-100 transition-opacity">
                          {message.role === 'user' && !isGenerating && editingMessageId !== message.id && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2"
                              onClick={() => startEditMessage(message)}
                            >
                              <Edit3 className="w-3 h-3 mr-1" />
                              编辑
                            </Button>
                          )}
                          {message.role === 'assistant' && !isGenerating && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2"
                              onClick={() => regenerate(message.id)}
                            >
                              <RefreshCw className="w-3 h-3 mr-1" />
                              重新回答
                            </Button>
                          )}
                          {message.role === 'assistant' && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2"
                              onClick={() => copyMessage(extractTextFromContent(message.content), message.id)}
                            >
                              {copiedId === message.id ? (
                                <Check className="w-3 h-3 mr-1" />
                              ) : (
                                <Copy className="w-3 h-3 mr-1" />
                              )}
                              {copiedId === message.id ? '已复制' : '复制'}
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}

              {/* 流式输出内容 */}
              {isGenerating && (
                <div className="flex gap-4 px-4">
                  <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center flex-shrink-0">
                    <Bot className="w-4 h-4" />
                  </div>
                  <div className="flex-1 space-y-2">
                    {/* 思考过程：生成中默认展开，用户可手动折叠 */}
                    {reasoningSteps.length > 0 && (
                      <ReasoningPanel
                        steps={reasoningSteps}
                        open={streamPanelOpen}
                        onToggle={() => setStreamPanelOpen((v) => !v)}
                      />
                    )}
                    {streamingContent ? (
                      <div className="bg-muted rounded-2xl px-4 py-3 max-w-full">
                        <div className="prose prose-sm dark:prose-invert max-w-none">
                          <MessageContent
                            content={streamingContent}
                            citationSources={streamingRagSources}
                          />
                        </div>
                      </div>
                    ) : (
                      !reasoningSteps.length && (
                        <div className="flex items-center gap-3 h-10 px-4 rounded-2xl bg-muted/80 max-w-[80%]">
                          <Loader2 className="w-4 h-4 animate-spin text-primary" />
                          <span className="text-sm text-muted-foreground">AI 正在思考</span>
                          <span className="flex gap-0.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: '0ms' }} />
                            <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: '120ms' }} />
                            <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: '240ms' }} />
                          </span>
                        </div>
                      )
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </ScrollArea>

        {/* 输入区域 */}
        <div className="border-t p-4">
          <div className="max-w-3xl mx-auto">
            {contextInfo && (
              <div className="flex items-center gap-2 mb-2 text-xs text-muted-foreground">
                <span
                  className={cn(
                    'inline-flex items-center gap-1 rounded-full px-2 py-0.5',
                    contextInfo.estimated_tokens > contextInfo.limit * 0.8
                      ? 'bg-amber-500/10 text-amber-600'
                      : 'bg-muted'
                  )}
                  title="本次对话估算的上下文 token 用量"
                >
                  上下文 ≈ {contextInfo.estimated_tokens.toLocaleString()} / {contextInfo.limit.toLocaleString()} tokens
                </span>
                {contextInfo.compressed && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-blue-500/10 px-2 py-0.5 text-blue-600">
                    已自动压缩历史
                  </span>
                )}
              </div>
            )}
            {pendingImages.length > 0 && (
              <div className="flex flex-wrap gap-2 px-1 pb-1">
                {pendingImages.map((img, i) => (
                  <div key={i} className="relative group">
                    <img
                      src={img.image_url?.url}
                      alt="待发送图片"
                      className="h-16 w-16 object-cover rounded-lg border border-border"
                    />
                    <button
                      type="button"
                      onClick={() => removeImage(i)}
                      className="absolute -top-1.5 -right-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-background border border-border text-foreground shadow-sm hover:bg-accent"
                      title="移除"
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="flex items-center gap-2 rounded-xl border bg-card px-4 py-3 focus-within:ring-2 focus-within:ring-primary/20 focus-within:border-primary">
              <label
                className="flex h-8 w-8 flex-shrink-0 cursor-pointer items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"
                title="上传图片（多模态对话，支持视觉模型）"
              >
                <Image className="h-4 w-4" />
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  className="hidden"
                  onChange={handleImageSelect}
                />
              </label>
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  currentConversation
                    ? '输入消息... (Shift+Enter 换行)'
                    : '先创建一个对话吧'
                }
                disabled={!currentConversation || isGenerating}
                rows={1}
                className={cn(
                  'flex-1 resize-none bg-transparent px-0 py-0',
                  'focus:outline-none focus:ring-0',
                  'disabled:opacity-50 disabled:cursor-not-allowed',
                  'min-h-[52px] max-h-[200px]'
                )}
                style={{ height: 'auto' }}
                onInput={(e) => {
                  const target = e.target as HTMLTextAreaElement
                  target.style.height = 'auto'
                  target.style.height = Math.min(target.scrollHeight, 200) + 'px'
                }}
              />
              <Button
                onClick={sendMessage}
                disabled={(!input.trim() && pendingImages.length === 0) || !currentConversation || isGenerating}
                size="icon"
                className="h-8 w-8 flex-shrink-0"
              >
                {isGenerating ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground text-center mt-2">
              AI 助手可能会产生不准确的信息，请验证重要信息。
            </p>
          </div>
        </div>
      </div>
      <ConfirmDialogComponent />
    </div>
  )
}
