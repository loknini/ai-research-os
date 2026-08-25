import { useState, useRef, useEffect } from 'react'
import { cn } from '@/utils'

export interface DropdownMenuItem {
  label: string
  icon?: React.ReactNode
  onClick: () => void
  variant?: 'default' | 'destructive'
  disabled?: boolean
}

interface DropdownMenuProps {
  /** 触发器（按钮、图标等），点击该区域会切换菜单开合 */
  trigger: React.ReactNode
  items: DropdownMenuItem[]
  /** 菜单对齐：right = 菜单右缘对齐触发器右缘，left = 菜单左缘对齐触发器左缘 */
  align?: 'left' | 'right'
  /** 菜单相对于触发器垂直偏移（像素） */
  sideOffset?: number
  className?: string
}

/**
 * 轻量下拉菜单：点击外部 / Esc 关闭、菜单项点击后自动收起。
 * 设计参考 ChatGPT / Claude / Cursor 等成熟 AI 工具的「⋯」更多菜单模式：
 * - 点击 trigger 切换 open 状态
 * - 菜单项含 default / destructive 两种视觉态
 * - 使用 mousedown 事件拦截以避免被 trigger 的 click 事件立即关掉
 */
export function DropdownMenu({
  trigger,
  items,
  align = 'right',
  sideOffset = 4,
  className,
}: DropdownMenuProps) {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!isOpen) return
    const handleMouseDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false)
    }
    // 使用 mousedown 早于 trigger 的 click 触发，避免点 trigger 时立刻被关掉
    document.addEventListener('mousedown', handleMouseDown)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleMouseDown)
      document.removeEventListener('keydown', handleKey)
    }
  }, [isOpen])

  return (
    <div className={cn('relative inline-block', className)} ref={containerRef}>
      <div
        onClick={(e) => {
          e.stopPropagation()
          setIsOpen((v) => !v)
        }}
        className="inline-flex"
      >
        {trigger}
      </div>
      {isOpen && (
        <div
          role="menu"
          style={{ top: `calc(100% + ${sideOffset}px)` }}
          className={cn(
            'absolute z-50 min-w-[160px] rounded-lg border border-border/60 bg-popover text-popover-foreground shadow-lg overflow-hidden',
            'py-1 origin-top-right',
            align === 'right' ? 'right-0' : 'left-0',
            'animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95'
          )}
        >
          {items.map((item, i) => (
            <button
              key={i}
              role="menuitem"
              onClick={(e) => {
                e.stopPropagation()
                if (item.disabled) return
                item.onClick()
                setIsOpen(false)
              }}
              disabled={item.disabled}
              className={cn(
                'w-full px-3 py-2 text-sm flex items-center gap-2 transition-colors text-left',
                'focus:outline-none',
                item.disabled && 'opacity-50 cursor-not-allowed',
                item.variant === 'destructive'
                  ? 'text-destructive hover:bg-destructive/10 focus-visible:bg-destructive/10'
                  : 'text-foreground hover:bg-accent focus-visible:bg-accent'
              )}
            >
              {item.icon && <span className="flex-shrink-0">{item.icon}</span>}
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}