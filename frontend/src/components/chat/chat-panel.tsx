import { useState, useRef, useEffect } from 'react'
import { useChatStore } from '@/stores/appStore'
import { useAIAgent } from '@/services/aiAgent'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/utils'
import {
  MessageSquare,
  X,
  Send,
  Bot,
  User,
  Loader2,
  Sparkles,
  ChevronDown,
  Command
} from 'lucide-react'

// 快捷命令
const QUICK_COMMANDS = [
  { label: '抓取论文', command: '抓取最新的CV论文', icon: '✨' },
  { label: '查看任务', command: '查看我的任务列表', icon: '📋' },
  { label: '创建任务', command: '创建一个任务：', icon: '✅' },
  { label: '总结论文', command: '帮我总结这篇论文：', icon: '📝' },
  { label: '同步实验', command: '从SwanLab获取实验数据', icon: '🔬' },
  { label: '创建笔记', command: '创建一个笔记：', icon: '📚' }
]

export function ChatPanel() {
  const [isOpen, setIsOpen] = useState(false)
  const [input, setInput] = useState('')
  const [showCommands, setShowCommands] = useState(false)
  const { messages, isProcessing } = useChatStore()
  const { sendMessage } = useAIAgent()
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isOpen])

  // 聚焦输入框
  useEffect(() => {
    if (isOpen && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [isOpen])

  const handleSend = async () => {
    if (!input.trim() || isProcessing) return
    
    const message = input.trim()
    setInput('')
    setShowCommands(false)
    await sendMessage(message)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleCommandClick = (command: string) => {
    setInput(command)
    setShowCommands(false)
    inputRef.current?.focus()
  }

  return (
    <>
      {/* 悬浮按钮 */}
      <button
        onClick={() => setIsOpen(true)}
        className={cn(
          'fixed bottom-6 right-6 w-14 h-14 rounded-full bg-primary text-primary-foreground shadow-lg hover:shadow-xl transition-all duration-300 flex items-center justify-center z-50',
          isOpen ? 'scale-0 opacity-0' : 'scale-100 opacity-100'
        )}
      >
        <MessageSquare className="w-6 h-6" />
      </button>

      {/* 聊天面板 */}
      <div
        className={cn(
          'fixed bottom-6 right-6 w-96 h-[600px] bg-card rounded-2xl shadow-2xl border flex flex-col z-50 transition-all duration-300',
          isOpen ? 'scale-100 opacity-100' : 'scale-0 opacity-0 pointer-events-none'
        )}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between p-4 border-b bg-primary/5 rounded-t-2xl">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <Bot className="w-5 h-5 text-primary-foreground" />
            </div>
            <div>
              <h3 className="font-semibold text-sm">AI 助手</h3>
              <p className="text-xs text-muted-foreground">随时为你提供帮助</p>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setIsOpen(false)}>
            <X className="w-4 h-4" />
          </Button>
        </div>

        {/* 消息列表 */}
        <ScrollArea ref={scrollRef} className="flex-1 p-4">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center text-muted-foreground space-y-4">
              <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center">
                <Sparkles className="w-8 h-8 text-primary" />
              </div>
              <div>
                <p className="font-medium">我是你的 AI 研究助手</p>
                <p className="text-sm mt-1">可以帮你：</p>
                <ul className="text-sm mt-2 space-y-1">
                  <li>• 抓取和总结论文</li>
                  <li>• 创建和管理任务</li>
                  <li>• 追踪实验进度</li>
                  <li>• 管理知识笔记</li>
                </ul>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={cn(
                    'flex gap-3',
                    msg.role === 'user' ? 'flex-row-reverse' : ''
                  )}
                >
                  <div
                    className={cn(
                      'w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0',
                      msg.role === 'user'
                        ? 'bg-primary'
                        : 'bg-muted'
                    )}
                  >
                    {msg.role === 'user' ? (
                      <User className="w-4 h-4 text-primary-foreground" />
                    ) : (
                      <Bot className="w-4 h-4" />
                    )}
                  </div>
                  <div
                    className={cn(
                      'max-w-[80%] rounded-2xl px-4 py-2 text-sm',
                      msg.role === 'user'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted'
                    )}
                  >
                    {msg.content}
                    {msg.metadata?.toolCalls && (
                      <div className="mt-2 pt-2 border-t border-primary-foreground/20 text-xs opacity-70">
                        使用了工具: {msg.metadata.toolCalls.join(', ')}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {isProcessing && (
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center">
                    <Bot className="w-4 h-4" />
                  </div>
                  <div className="bg-muted rounded-2xl px-4 py-3">
                    <Loader2 className="w-4 h-4 animate-spin" />
                  </div>
                </div>
              )}
            </div>
          )}
        </ScrollArea>

        {/* 快捷命令 */}
        {showCommands && (
          <div className="border-t p-2 bg-muted/30">
            <div className="grid grid-cols-2 gap-2">
              {QUICK_COMMANDS.map((cmd) => (
                <button
                  key={cmd.label}
                  onClick={() => handleCommandClick(cmd.command)}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg bg-background hover:bg-muted transition-colors text-left text-sm"
                >
                  <span>{cmd.icon}</span>
                  <span className="truncate">{cmd.label}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 输入区域 */}
        <div className="p-4 border-t space-y-2">
          <div className="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowCommands(!showCommands)}
              className="text-muted-foreground"
            >
              <Command className="w-4 h-4 mr-1" />
              命令
              <ChevronDown className={cn('w-3 h-3 ml-1 transition-transform', showCommands && 'rotate-180')} />
            </Button>
          </div>
          <div className="flex gap-2">
            <Input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入消息..."
              className="flex-1"
            />
            <Button
              onClick={handleSend}
              disabled={!input.trim() || isProcessing}
              size="icon"
            >
              {isProcessing ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </Button>
          </div>
        </div>
      </div>
    </>
  )
}
