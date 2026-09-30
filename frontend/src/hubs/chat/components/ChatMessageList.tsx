import type { Dispatch, RefObject, SetStateAction } from 'react'
import { Bot, Check, ChevronLeft, ChevronRight, Copy, Edit3, Loader2, RefreshCw, Sparkles, User } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn, stripToolCallTrace } from '@/utils'
import type { Conversation, Message, RagSource, ReasoningStep } from '../types'
import type { GenPhase } from '../services/chatGenerationManager'
import { AssistantMessageBody } from './AssistantMessageBody'
import { ReasoningPanel } from './ReasoningPanel'
import MessageContent from './MessageContent'
import { extractTextFromContent } from '../messageUtils'

interface ChatMessageListProps {
  scrollRef: RefObject<HTMLDivElement>
  conversation: Conversation | null
  onSuggestedPrompt: (prompt: string) => void
  editingMessageId: string | null
  editBuffer: string
  onEditBufferChange: Dispatch<SetStateAction<string>>
  onCancelEdit: () => void
  onEditMessage: (messageId: string, content: string) => void
  isGenerating: boolean
  onSwitchBranch: (messageId: string) => void
  onStartEditMessage: (message: Message) => void
  onRegenerate: (messageId: string) => void
  copiedId: string | null
  onCopyMessage: (content: string, id: string) => void
  reasoningSteps: ReasoningStep[]
  streamPanelOpen: boolean
  onToggleStreamPanel: () => void
  streamingContent: string
  streamingRagSources: RagSource[]
  generationPhase: GenPhase | null
  generationElapsed: number
}

export function ChatMessageList({
  scrollRef,
  conversation,
  onSuggestedPrompt,
  editingMessageId,
  editBuffer,
  onEditBufferChange,
  onCancelEdit,
  onEditMessage,
  isGenerating,
  onSwitchBranch,
  onStartEditMessage,
  onRegenerate,
  copiedId,
  onCopyMessage,
  reasoningSteps,
  streamPanelOpen,
  onToggleStreamPanel,
  streamingContent,
  streamingRagSources,
  generationPhase,
  generationElapsed,
}: ChatMessageListProps) {
  return (
    <>
        {/* 消息列表 */}
        <ScrollArea ref={scrollRef} className="flex-1">
          {!conversation ? (
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
                      onSuggestedPrompt(`帮我${item.desc}`)
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
              {conversation.messages
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
                                onChange={(e) => onEditBufferChange(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                                    onEditMessage(message.id, editBuffer)
                                  }
                                  if (e.key === 'Escape') onCancelEdit()
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
                                  onClick={() => onEditMessage(message.id, editBuffer)}
                                >
                                  保存并重答
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 px-3"
                                  onClick={onCancelEdit}
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
                                  onSwitchBranch(sibs[cur - 1])
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
                                  onSwitchBranch(sibs[cur + 1])
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
                              onClick={() => onStartEditMessage(message)}
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
                              onClick={() => onRegenerate(message.id)}
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
                              onClick={() => onCopyMessage(stripToolCallTrace(extractTextFromContent(message.content)), message.id)}
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
                        onToggle={onToggleStreamPanel}
                      />
                    )}
                    {streamingContent ? (
                      <div className="bg-muted rounded-2xl px-4 py-3 max-w-full">
                        <div className="prose prose-sm dark:prose-invert max-w-none">
                          <MessageContent
                            content={stripToolCallTrace(streamingContent)}
                            citationSources={streamingRagSources}
                          />
                        </div>
                      </div>
                    ) : (
                      !reasoningSteps.length && (
                        <div className="flex items-center gap-3 h-10 px-4 rounded-2xl bg-muted/80 max-w-[80%]">
                          <Loader2 className="w-4 h-4 animate-spin text-primary" />
                          <span className="text-sm text-muted-foreground">
                            {generationPhase === 'retrieving'
                              ? '正在检索文档'
                              : generationPhase === 'working'
                                ? '正在调用工具'
                                : 'AI 正在思考'}
                            …{generationElapsed}s
                            {generationElapsed >= 60 && '（仍在处理，可取消）'}
                          </span>
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
    </>
  )
}
