import type { Dispatch, PointerEventHandler, SetStateAction } from 'react'
import { Edit3, Loader2, MessageSquare, MoreHorizontal, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/utils'
import type { Conversation } from '../types'

export interface ConversationContextMenu {
  x: number
  y: number
  conv: Conversation
}

interface ChatSidebarProps {
  drawerOpen: boolean
  onDrawerClose: () => void
  sidebarCollapsed: boolean
  isResizing: boolean
  width: number
  onResizeStart: PointerEventHandler<HTMLDivElement>
  onResetWidth: () => void
  conversations: Conversation[]
  currentConversationId: string | null
  isLoading: boolean
  editingId: string | null
  editTitle: string
  activeMenuId: string | null
  onNewConversation: () => void
  onSelectConversation: (id: string) => void
  onContextMenu: Dispatch<SetStateAction<ConversationContextMenu | null>>
  onActiveMenuChange: Dispatch<SetStateAction<string | null>>
  onEditTitleChange: Dispatch<SetStateAction<string>>
  onSaveTitle: (id: string) => void
  onStartEditTitle: (conversation: Conversation) => void
  onDeleteConversation: (id: string) => void
  onCancelEdit: () => void
}

export function ChatSidebar({
  drawerOpen,
  onDrawerClose,
  sidebarCollapsed,
  isResizing,
  width,
  onResizeStart,
  onResetWidth,
  conversations,
  currentConversationId,
  isLoading,
  editingId,
  editTitle,
  activeMenuId,
  onNewConversation,
  onSelectConversation,
  onContextMenu,
  onActiveMenuChange,
  onEditTitleChange,
  onSaveTitle,
  onStartEditTitle,
  onDeleteConversation,
  onCancelEdit,
}: ChatSidebarProps) {
  return (
    <>
      {/* 抽屉遮罩 */}
      {drawerOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/20 backdrop-blur-[1px]"
          onClick={onDrawerClose}
          aria-hidden
        />
      )}
      {/* 左侧会话列表 — 悬浮抽屉，可拖拽调宽 */}
      <div
        id="chat-drawer"
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex flex-col bg-card border-r shadow-xl',
          'transition-transform duration-200 ease-out',
          drawerOpen ? 'translate-x-0' : '-translate-x-full',
          isResizing && 'transition-none'
        )}
        style={{ width: width }}
      >
        {/* 拖拽调宽手柄：右缘竖条，双击复位 */}
        {!sidebarCollapsed && (
          <div
            onPointerDown={onResizeStart}
            onDoubleClick={onResetWidth}
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
            onClick={onNewConversation}
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
                onClick={() => {
                  onActiveMenuChange(null)
                  onSelectConversation(conv.id)
                }}
                onContextMenu={(e) => {
                  e.preventDefault()
                  onContextMenu({ x: e.clientX, y: e.clientY, conv })
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
                      onChange={(e) => onEditTitleChange(e.target.value)}
                      onBlur={() => onSaveTitle(conv.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') onSaveTitle(conv.id)
                        if (e.key === 'Escape') onCancelEdit()
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
                  <div className="relative flex-shrink-0" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => onActiveMenuChange(activeMenuId === conv.id ? null : conv.id)}
                      className={cn(
                        'h-7 w-7 inline-flex items-center justify-center rounded-md transition-colors',
                        'opacity-0 group-hover:opacity-100 focus-visible:opacity-100',
                        activeMenuId === conv.id && 'opacity-100',
                        currentConversationId === conv.id
                          ? 'hover:bg-primary/20 text-primary-foreground'
                          : 'hover:bg-accent text-foreground'
                      )}
                      aria-label={`更多操作 ${conv.title}`}
                      aria-haspopup="menu"
                      aria-expanded={activeMenuId === conv.id}
                    >
                      <MoreHorizontal className="w-4 h-4" />
                    </button>
                    {activeMenuId === conv.id && (
                      <div
                        id={`conv-menu-${conv.id}`}
                        role="menu"
                        className="absolute right-0 top-full mt-1 z-20 w-36 rounded-lg border border-border/60 bg-popover shadow-lg overflow-hidden py-1"
                      >
                        <button
                          role="menuitem"
                          onClick={() => {
                            onActiveMenuChange(null)
                            onStartEditTitle(conv)
                          }}
                          className="w-full px-3 py-1.5 text-sm flex items-center gap-2 hover:bg-accent text-left text-black dark:text-white"
                        >
                          <Edit3 className="w-3.5 h-3.5 text-black dark:text-white" />
                          <span className="text-black dark:text-white">重命名</span>
                        </button>
                        <button
                          role="menuitem"
                          onClick={() => {
                            onActiveMenuChange(null)
                            onDeleteConversation(conv.id)
                          }}
                          className="w-full px-3 py-1.5 text-sm flex items-center gap-2 hover:bg-accent text-left text-destructive"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                          删除
                        </button>
                      </div>
                    )}
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

      </div>
    </>
  )
}
