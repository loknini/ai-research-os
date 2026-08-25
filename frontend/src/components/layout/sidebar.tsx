import { useState, useRef, useCallback, useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import { useAppStore } from '@/stores/appStore'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/utils'
import { ThemeToggle } from '@/components/layout/theme-toggle'
import { Loader2, ChevronLeft, ChevronRight, Atom } from 'lucide-react'
// 导航 manifest：一级导航结构统一由配置文件驱动，新增业务域只需改 navigation.ts
import { navGroups } from '@/config/navigation'

const MIN_EXPANDED_WIDTH = 180
const MAX_WIDTH = 360
const COLLAPSED_WIDTH = 72
const AUTO_COLLAPSE_THRESHOLD = 110

export function Sidebar() {
  const { isConnected, isConnecting, sidebarCollapsed, sidebarWidth, toggleSidebar, setSidebarCollapsed, setSidebarWidth } = useAppStore()
  const [isResizing, setIsResizing] = useState(false)
  const startXRef = useRef(0)
  const startWidthRef = useRef(sidebarWidth)

  const handleResizeStart = useCallback(
    (clientX: number) => {
      startXRef.current = clientX
      startWidthRef.current = sidebarCollapsed ? COLLAPSED_WIDTH : sidebarWidth
      setIsResizing(true)
    },
    [sidebarCollapsed, sidebarWidth]
  )

  const handleResizeMove = useCallback(
    (clientX: number) => {
      if (!isResizing) return
      const delta = clientX - startXRef.current
      const rawWidth = startWidthRef.current + delta

      if (sidebarCollapsed) {
        if (rawWidth > AUTO_COLLAPSE_THRESHOLD) {
          setSidebarWidth(rawWidth)
          setSidebarCollapsed(false)
        }
      } else {
        if (rawWidth < AUTO_COLLAPSE_THRESHOLD) {
          setSidebarCollapsed(true)
        } else {
          setSidebarWidth(Math.min(Math.max(rawWidth, MIN_EXPANDED_WIDTH), MAX_WIDTH))
        }
      }
    },
    [isResizing, sidebarCollapsed, setSidebarCollapsed, setSidebarWidth]
  )

  const handleResizeEnd = useCallback(() => {
    setIsResizing(false)
  }, [])

  useEffect(() => {
    if (!isResizing) return

    const onMouseMove = (e: MouseEvent) => handleResizeMove(e.clientX)
    const onMouseUp = () => handleResizeEnd()
    const onTouchMove = (e: TouchEvent) => {
      if (e.touches[0]) handleResizeMove(e.touches[0].clientX)
    }
    const onTouchEnd = () => handleResizeEnd()

    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    document.addEventListener('touchmove', onTouchMove)
    document.addEventListener('touchend', onTouchEnd)

    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
      document.removeEventListener('touchmove', onTouchMove)
      document.removeEventListener('touchend', onTouchEnd)
    }
  }, [isResizing, handleResizeMove, handleResizeEnd])

  const currentWidth = sidebarCollapsed ? COLLAPSED_WIDTH : sidebarWidth

  return (
    <aside
      className={cn(
        'relative flex flex-col h-screen border-r border-border/50 glass transition-[width] duration-200 ease-out select-none',
        isResizing && 'transition-none'
      )}
      style={{ width: currentWidth }}
      aria-expanded={!sidebarCollapsed}
    >
      {/* Logo */}
      <div
        className={cn(
          'border-b border-border/50',
          sidebarCollapsed ? 'p-4 flex justify-center' : 'px-5 py-4'
        )}
      >
        <div
          className={cn(
            'flex items-center',
            sidebarCollapsed ? 'flex-col gap-3' : 'justify-between gap-3'
          )}
        >
          <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center shadow-sm shrink-0">
            <Atom className="w-6 h-6 text-primary-foreground" strokeWidth={1.5} />
          </div>
            {!sidebarCollapsed && (
              <h1 className="font-display font-bold text-lg leading-tight tracking-tight truncate">
                Research OS
              </h1>
            )}
          </div>

          <Button
            variant="ghost"
            size="icon"
            className={cn(
              'h-7 w-7 rounded-lg text-muted-foreground hover:text-foreground shrink-0',
              sidebarCollapsed && 'h-8 w-8'
            )}
            onClick={toggleSidebar}
            aria-label={sidebarCollapsed ? '展开侧边栏' : '折叠侧边栏'}
            title={sidebarCollapsed ? '展开侧边栏' : '折叠侧边栏'}
          >
            {sidebarCollapsed ? (
              <ChevronRight className="w-4 h-4" />
            ) : (
              <ChevronLeft className="w-4 h-4" />
            )}
          </Button>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-3 space-y-4 overflow-y-auto overflow-x-hidden">
        {navGroups.map((group) => (
          <div key={group.id} className="space-y-1">
            {!sidebarCollapsed && (
              <p className="px-3 pt-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                {group.label}
              </p>
            )}
            {group.items.map((item) => (
              <NavLink
                key={item.id}
                to={item.path}
                title={sidebarCollapsed ? `${item.name} · ${item.description}` : undefined}
                className={({ isActive }) =>
                  cn(
                    'flex items-center rounded-lg transition-colors group',
                    sidebarCollapsed ? 'justify-center px-2 py-3' : 'gap-3 px-4 py-3',
                    isActive
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                  )
                }
              >
                <item.icon className="w-5 h-5 shrink-0" />
                {!sidebarCollapsed && (
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{item.name}</div>
                    <div className="text-xs opacity-70 truncate">{item.description}</div>
                  </div>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* Footer - 连接状态卡片 + 设置 */}
      <div
        className={cn(
          'border-t border-border/50 space-y-3',
          sidebarCollapsed ? 'p-3 flex flex-col items-center' : 'p-4'
        )}
      >
        <div
          className={cn(
            'rounded-lg bg-muted',
            sidebarCollapsed ? 'p-2 flex justify-center' : 'p-3'
          )}
          title={
            sidebarCollapsed
              ? `后端状态：${isConnecting ? '连接中' : isConnected ? '在线' : '离线'}`
              : undefined
          }
        >
          {sidebarCollapsed ? (
            <div className="flex items-center justify-center">
              {isConnecting ? (
                <Loader2 className="w-4 h-4 animate-spin text-yellow-600" />
              ) : isConnected ? (
                <span className="w-2.5 h-2.5 rounded-full bg-green-500" />
              ) : (
                <span className="w-2.5 h-2.5 rounded-full bg-red-500" />
              )}
            </div>
          ) : (
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">后端状态</p>
              {isConnecting ? (
                <Badge
                  variant="secondary"
                  className="bg-yellow-500/10 text-yellow-600 flex items-center gap-1.5"
                >
                  <Loader2 className="w-3 h-3 animate-spin" />
                  <span>连接中</span>
                </Badge>
              ) : isConnected ? (
                <Badge
                  variant="default"
                  className="bg-green-500/10 text-green-600 hover:bg-green-500/20"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-green-500 mr-1.5" />
                  在线
                </Badge>
              ) : (
                <Badge
                  variant="destructive"
                  className="bg-red-500/10 text-red-600 hover:bg-red-500/20"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-red-500 mr-1.5" />
                  离线
                </Badge>
              )}
            </div>
          )}
        </div>

        <ThemeToggle collapsed={sidebarCollapsed} />
      </div>

      {/* Resize handle */}
      <div
        className="absolute top-0 right-0 h-full w-3 cursor-col-resize z-10 flex justify-end group"
        onMouseDown={(e) => handleResizeStart(e.clientX)}
        onTouchStart={(e) => {
          const touch = e.touches[0]
          if (touch) handleResizeStart(touch.clientX)
        }}
        role="separator"
        aria-label="调整侧边栏宽度"
        aria-orientation="vertical"
      >
        <div className="w-[3px] h-full bg-transparent group-hover:bg-primary/30 transition-colors" />
      </div>
    </aside>
  )
}
