import type { Dispatch, SetStateAction } from 'react'
import { BookOpen, ChevronDown, ChevronLeft, PanelLeft, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ContextRing } from './ContextRing'
import { cn } from '@/utils'

interface BranchTip {
  index: number
  count: number
  role: string
}

interface ContextInfo {
  estimated_tokens: number
  limit: number
  compressed: boolean
}

interface RagIndexSource {
  id: string
  name: string
  kind?: string
}

interface ChatHeaderProps {
  drawerOpen: boolean
  onToggleDrawer: () => void
  sidebarCollapsed: boolean
  onToggleSidebar: () => void
  conversationTitle?: string
  hasConversation: boolean
  onNewConversation: () => void
  branchTip: BranchTip | null
  contextInfo: ContextInfo | null
  contextExpanded: boolean
  onToggleContext: () => void
  ragEnabled: boolean
  onToggleRag: () => void
  ragPickerOpen: boolean
  onToggleRagPicker: () => void
  ragSources: RagIndexSource[]
  selectedSourceIds: string[]
  onSelectedSourceIdsChange: Dispatch<SetStateAction<string[]>>
}

export function ChatHeader({
  drawerOpen,
  onToggleDrawer,
  sidebarCollapsed,
  onToggleSidebar,
  conversationTitle,
  hasConversation,
  onNewConversation,
  branchTip,
  contextInfo,
  contextExpanded,
  onToggleContext,
  ragEnabled,
  onToggleRag,
  ragPickerOpen,
  onToggleRagPicker,
  ragSources,
  selectedSourceIds,
  onSelectedSourceIdsChange,
}: ChatHeaderProps) {
  return (
    <>
        {/* 顶部栏 */}
        <div className="h-14 border-b flex items-center justify-between px-4">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={onToggleDrawer}
              aria-label={drawerOpen ? '收起对话列表' : '展开对话列表'}
              title={drawerOpen ? '收起对话列表' : '展开对话列表'}
            >
              <PanelLeft className="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onToggleSidebar}
              className="lg:hidden"
            >
              <ChevronLeft
                className={cn('w-4 h-4 transition-transform', sidebarCollapsed && 'rotate-180')}
              />
            </Button>
            <h2 className="font-semibold">
              {conversationTitle || 'AI 助手'}
            </h2>
            {/* 会话内新建对话：免去点开列表再新建（旧生成在后台继续跑，由全局观察器提醒） */}
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              title="新建对话"
              onClick={onNewConversation}
            >
              <Plus className="w-4 h-4" />
            </Button>
            {branchTip && (
              <span
                className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
                title={`当前显示该${branchTip.role === 'user' ? '提问' : '回复'}的第 ${branchTip.index}/${branchTip.count} 个版本`}
              >
                版本 {branchTip.index}/{branchTip.count}
              </span>
            )}
          </div>
          {hasConversation && (
            <div className="flex items-center gap-2">
              {contextInfo && (
                <ContextRing
                  value={contextInfo.estimated_tokens}
                  limit={contextInfo.limit}
                  compressed={contextInfo.compressed}
                  expanded={contextExpanded}
                  onToggle={onToggleContext}
                />
              )}
              {/* 知识增强开关 + 来源筛选 */}
              <div className="flex items-center gap-1.5">
                <Button
                  variant={ragEnabled ? 'default' : 'ghost'}
                  size="sm"
                  onClick={onToggleRag}
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
                      onClick={onToggleRagPicker}
                      title="选择要检索的文档源（默认全部）"
                    >
                      来源 {selectedSourceIds.length === ragSources.length && ragSources.length > 0 ? '全部' : `${selectedSourceIds.length}/${ragSources.length || 0}`}
                      <ChevronDown className="w-3.5 h-3.5 ml-1" />
                    </Button>
                    {ragPickerOpen && (
                      <div
                        id="rag-source-picker"
                        className="absolute right-0 top-full mt-1 z-30 w-64 rounded-lg border border-border/60 bg-popover text-popover-foreground shadow-lg p-2 max-h-72 overflow-auto"
                      >
                        {ragSources.length === 0 ? (
                          <p className="text-xs text-muted-foreground px-1 py-2">
                            暂无已索引文档
                          </p>
                        ) : (
                          <>
                            <label className="flex items-center gap-2 px-1.5 py-1.5 rounded hover:bg-accent cursor-pointer text-sm font-medium border-b border-border/40 mb-1">
                              <input
                                type="checkbox"
                                checked={selectedSourceIds.length === ragSources.length && ragSources.length > 0}
                                ref={(el) => {
                                  if (el) el.indeterminate = selectedSourceIds.length > 0 && selectedSourceIds.length < ragSources.length
                                }}
                                onChange={() => {
                                  if (selectedSourceIds.length === ragSources.length) onSelectedSourceIdsChange([])
                                  else onSelectedSourceIdsChange(ragSources.map((s) => s.id))
                                }}
                              />
                              <span>全部来源 {selectedSourceIds.length === ragSources.length ? '(已选全部)' : ` (已选 ${selectedSourceIds.length}/${ragSources.length})`}</span>
                            </label>
                            {ragSources.map((s) => {
                              const checked = selectedSourceIds.includes(s.id)
                              return (
                                <label
                                  key={s.id}
                                  className="flex items-center gap-2 px-1.5 py-1.5 rounded hover:bg-accent cursor-pointer text-sm"
                                >
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => {
                                      onSelectedSourceIdsChange((prev) => (checked ? prev.filter((id) => id !== s.id) : [...prev, s.id]))
                                    }}
                                  />
                                  <span className="truncate">{s.name}</span>
                                  <span className="ml-auto text-[10px] text-muted-foreground shrink-0">
                                    {s.kind === 'paper' ? '论文库' : s.kind === 'web' ? '网页' : '本地'}
                                  </span>
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
            </div>
          )}
        </div>
    </>
  )
}
