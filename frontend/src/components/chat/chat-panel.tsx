import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, ChevronDown, Command, ExternalLink, Loader2, MessageSquare, Send, Settings, Sparkles, User, X } from 'lucide-react'
import { useAppStore } from '@/stores/appStore'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn, generateId } from '@/utils'
import {
  addMessageAPI, createConversationAPI, fetchConversationDetail, updateConversationAPI
} from '@/hubs/chat/services/chatApi'
import { chatGenerationManager } from '@/hubs/chat/services/chatGenerationManager'
import type { Conversation, Message } from '@/hubs/chat/types'

const QUICK_PROMPTS = [
  { label: '研读论文', prompt: '请帮我设计一份论文研读计划，并说明需要我提供哪些论文。', icon: '✨' },
  { label: '梳理任务', prompt: '请查看并帮我梳理当前任务，指出优先级和下一步。', icon: '📋' },
  { label: '创建任务', prompt: '我想创建一个任务，请先询问我缺少的必要信息。', icon: '✅' },
  { label: '知识综合', prompt: '请帮我把现有研究材料综合成结构化知识，并告诉我需要选择哪些笔记。', icon: '📚' }
]

function contentText(content: Message['content']): string {
  if (typeof content === 'string') return content
  return content.filter(part => part.type === 'text').map(part => part.text || '').join('\n') || '[图片消息]'
}

export function ChatPanel() {
  const navigate = useNavigate()
  const conversationId = useAppStore(state => state.chatConversationId)
  const setConversationId = useAppStore(state => state.setChatConversationId)
  const [isOpen, setIsOpen] = useState(false)
  const [input, setInput] = useState('')
  const [showPrompts, setShowPrompts] = useState(false)
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [streaming, setStreaming] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [configured, setConfigured] = useState<boolean | null>(null)
  const [error, setError] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async (id: string) => {
    const detail = await fetchConversationDetail(id)
    if (detail) setConversation(detail)
    else {
      setConversation(null)
      if (useAppStore.getState().chatConversationId === id) setConversationId(null)
    }
  }, [setConversationId])

  useEffect(() => {
    if (!isOpen) return
    fetch('/api/llm/status').then(response => response.json()).then(data =>
      setConfigured(data.configured === true)).catch(() => setConfigured(false))
    if (conversationId) void load(conversationId)
    else setConversation(null)
  }, [conversationId, isOpen, load])

  useEffect(() => {
    if (!conversationId) { setIsGenerating(false); setStreaming(''); return }
    let flushing = false
    const sync = async () => {
      const generation = chatGenerationManager.getActive(conversationId)
      if (!generation) { setIsGenerating(false); return }
      setIsGenerating(generation.status === 'running')
      setStreaming(generation.streamingContent)
      if (generation.status !== 'running' && !flushing) {
        flushing = true
        await load(conversationId)
        setStreaming(''); setIsGenerating(false)
        chatGenerationManager.clear(conversationId)
        flushing = false
      }
    }
    const unsubscribe = chatGenerationManager.subscribe(conversationId, () => void sync())
    void sync()
    return unsubscribe
  }, [conversationId, load])

  useEffect(() => {
    if (!isOpen) return
    const timer = window.setTimeout(() => {
      const viewport = scrollRef.current?.querySelector<HTMLElement>('[data-radix-scroll-area-viewport]')
      if (viewport) viewport.scrollTop = viewport.scrollHeight
      inputRef.current?.focus()
    }, 30)
    return () => window.clearTimeout(timer)
  }, [conversation?.messages, streaming, isOpen])

  const ensureConversation = async (): Promise<Conversation> => {
    if (conversationId) {
      const existing = conversation?.id === conversationId
        ? conversation
        : await fetchConversationDetail(conversationId)
      if (existing) return existing
    }
    const created = await createConversationAPI({
      id: generateId(), title: '新对话', createdAt: Date.now(), updatedAt: Date.now(),
      messages: [{ id: generateId(), role: 'system',
        content: '你是 AI Research OS 的 AI 助手，帮助研究人员管理论文、任务、项目和实验。',
        timestamp: Date.now() }]
    })
    if (!created) throw new Error('创建会话失败')
    setConversationId(created.id); setConversation(created)
    return created
  }

  const send = async () => {
    const text = input.trim()
    if (!text || isGenerating) return
    setError(''); setInput(''); setShowPrompts(false)
    try {
      const current = await ensureConversation()
      const message: Message = { id: generateId(), role: 'user', content: text, timestamp: Date.now() }
      if (!await addMessageAPI(current.id, message)) throw new Error('保存消息失败')
      const messages = [...current.messages, message]
      setConversation({ ...current, messages })
      if (messages.filter(item => item.role === 'user').length === 1) {
        await updateConversationAPI(current.id, { title: text.slice(0, 20) + (text.length > 20 ? '…' : '') })
      }
      setIsGenerating(true)
      void chatGenerationManager.start(messages, current.id)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '发送失败')
    }
  }

  const visibleMessages = (conversation?.messages || []).filter(message => message.role !== 'system').slice(-10)

  return <>
    <button aria-label="打开 AI 助手" onClick={() => setIsOpen(true)} className={cn(
      'fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-all hover:shadow-xl',
      isOpen ? 'scale-0 opacity-0' : 'scale-100 opacity-100')}>
      <MessageSquare className="h-6 w-6" />
    </button>
    <div className={cn(
      'fixed bottom-6 right-6 z-50 flex h-[620px] w-96 flex-col rounded-2xl border bg-card shadow-2xl transition-all',
      isOpen ? 'scale-100 opacity-100' : 'pointer-events-none scale-0 opacity-0')}>
      <div className="flex items-center justify-between rounded-t-2xl border-b bg-primary/5 p-4">
        <div className="flex items-center gap-2"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary"><Bot className="h-5 w-5 text-primary-foreground" /></div>
          <div><h3 className="text-sm font-semibold">AI 助手</h3><p className="text-xs text-muted-foreground">与 Chat Hub 共享真实 LLM 会话</p></div></div>
        <div className="flex gap-1"><Button variant="ghost" size="sm" title="展开完整对话" onClick={() => navigate(conversationId ? `/chat?conv=${conversationId}` : '/chat')}><ExternalLink className="h-4 w-4" /></Button>
          <Button variant="ghost" size="sm" onClick={() => setIsOpen(false)}><X className="h-4 w-4" /></Button></div>
      </div>
      {configured === false && <div className="m-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs">
        尚未配置 LLM，消息无法生成回答。<Button className="ml-1 h-auto p-0" variant="link" onClick={() => navigate('/settings')}><Settings className="mr-1 h-3 w-3" />去设置</Button>
      </div>}
      <ScrollArea ref={scrollRef} className="flex-1 p-4">
        {visibleMessages.length === 0 && !streaming ? <div className="flex h-full flex-col items-center justify-center space-y-3 text-center text-muted-foreground">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10"><Sparkles className="h-8 w-8 text-primary" /></div>
          <div><p className="font-medium">真实 LLM 研究助手</p><p className="mt-1 text-sm">这里的消息、工具结果和完整 Chat 页面保持一致。</p></div>
        </div> : <div className="space-y-4">
          {visibleMessages.map(message => <div key={message.id} className={cn('flex gap-3', message.role === 'user' && 'flex-row-reverse')}>
            <div className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-lg', message.role === 'user' ? 'bg-primary' : 'bg-muted')}>
              {message.role === 'user' ? <User className="h-4 w-4 text-primary-foreground" /> : <Bot className="h-4 w-4" />}
            </div><div className={cn('max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm', message.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted')}>{contentText(message.content)}</div>
          </div>)}
          {(isGenerating || streaming) && <div className="flex gap-3"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted"><Bot className="h-4 w-4" /></div>
            <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-muted px-4 py-2 text-sm">{streaming || <Loader2 className="h-4 w-4 animate-spin" />}</div></div>}
        </div>}
      </ScrollArea>
      {error && <div className="px-4 text-xs text-destructive">{error}</div>}
      {showPrompts && <div className="grid grid-cols-2 gap-2 border-t bg-muted/30 p-2">
        {QUICK_PROMPTS.map(item => <button key={item.label} onClick={() => { setInput(item.prompt); setShowPrompts(false); inputRef.current?.focus() }}
          className="flex items-center gap-2 rounded-lg bg-background px-3 py-2 text-left text-sm hover:bg-muted"><span>{item.icon}</span><span>{item.label}</span></button>)}
      </div>}
      <div className="space-y-2 border-t p-4"><Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => setShowPrompts(value => !value)}>
        <Command className="mr-1 h-4 w-4" />提示词<ChevronDown className={cn('ml-1 h-3 w-3 transition-transform', showPrompts && 'rotate-180')} /></Button>
        <div className="flex gap-2"><Input ref={inputRef} value={input} onChange={event => setInput(event.target.value)}
          onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }} placeholder="输入消息……" />
          <Button size="icon" disabled={!input.trim() || isGenerating || configured === false} onClick={() => void send()}>{isGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}</Button></div>
      </div>
    </div>
  </>
}
