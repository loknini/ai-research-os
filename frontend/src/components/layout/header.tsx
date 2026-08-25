import { useState, useRef, useEffect, useLayoutEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { KeyRound, ChevronDown, Copy, Check, LogOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/stores/appStore'
import { toast } from '@/components/ui/toast'

interface HeaderProps {
  title: string
  description?: string
  actions?: React.ReactNode
}

// 与后端 deps.MIN_KEY_LEN 保持一致。
const MIN_KEY_LEN = 4

interface DropdownPosition {
  top: number
  left: number
}

const DROPDOWN_MARGIN = 8
const DROPDOWN_MIN_WIDTH = 288 // w-72 = 18rem

/** 当前空间指示 + 切换 / 新建 / 分享入口。渲染于每个 Hub 顶栏右侧。 */
function SpaceIndicator() {
  const spaceKey = useAppStore((s) => s.spaceKey)
  const setSpace = useAppStore((s) => s.setSpace)
  const clearSpace = useAppStore((s) => s.clearSpace)
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [position, setPosition] = useState<DropdownPosition>({ top: 0, left: 0 })
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const normalized = spaceKey.trim().toLowerCase()
  const display = normalized === '__default__' ? '默认空间' : spaceKey || '未选择空间'

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current?.getBoundingClientRect()
    if (!trigger) return

    const dropdown = dropdownRef.current
    const width = Math.min(
      dropdown?.offsetWidth || DROPDOWN_MIN_WIDTH,
      window.innerWidth - DROPDOWN_MARGIN * 2
    )
    const height = dropdown?.offsetHeight || 0

    // 默认左对齐触发按钮
    let left = trigger.left
    // 右边界溢出时，改为右对齐触发按钮
    if (left + width > window.innerWidth - DROPDOWN_MARGIN) {
      left = trigger.right - width
    }
    // 保证左右都留出边距
    left = Math.max(DROPDOWN_MARGIN, Math.min(left, window.innerWidth - width - DROPDOWN_MARGIN))

    // 默认在触发按钮下方
    let top = trigger.bottom + DROPDOWN_MARGIN
    // 下方溢出时，翻转到触发按钮上方
    if (height && top + height > window.innerHeight - DROPDOWN_MARGIN) {
      top = trigger.top - height - DROPDOWN_MARGIN
    }
    // 保证顶部不超出视口
    top = Math.max(DROPDOWN_MARGIN, top)

    setPosition({ top, left })
  }, [])

  const handleToggle = () => {
    if (!open) {
      updatePosition()
    }
    setOpen((o) => !o)
  }

  const shareLink = () => {
    if (!spaceKey.trim()) {
      toast({ title: '尚未选择空间', variant: 'error' })
      return
    }
    const url = `${window.location.origin}${window.location.pathname}?space=${encodeURIComponent(
      spaceKey.trim()
    )}`
    navigator.clipboard?.writeText(url)
    toast({ title: '分享链接已复制', description: '打开链接将自动进入当前空间' })
    setOpen(false)
  }

  const switchSpace = () => {
    const k = input.trim()
    if (k.length < MIN_KEY_LEN) {
      toast({ title: `口令至少 ${MIN_KEY_LEN} 个字符`, variant: 'error' })
      return
    }
    setSpace(k)
    setInput('')
    setOpen(false)
    toast({ title: '已切换到新空间', description: `${k} 的数据相互隔离` })
  }

  useLayoutEffect(() => {
    if (open) updatePosition()
  }, [open, updatePosition])

  useEffect(() => {
    if (!open) return

    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node
      if (
        dropdownRef.current?.contains(target) ||
        triggerRef.current?.contains(target)
      ) {
        return
      }
      setOpen(false)
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }

    const handleResize = () => setOpen(false)

    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleKeyDown)
    window.addEventListener('resize', handleResize)

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('resize', handleResize)
    }
  }, [open])

  const dropdown = (
    <div
      ref={dropdownRef}
      className="fixed z-[100] w-72 max-w-[calc(100vw-1rem)] max-h-[calc(100vh-1rem)] overflow-y-auto rounded-2xl border border-border/50 glass p-1 shadow-xl"
      style={{ top: position.top, left: position.left }}
      role="dialog"
      aria-label="空间切换"
    >
      {/* 当前空间 */}
      <div className="px-3 pt-3 pb-2">
        <p className="text-xs text-muted-foreground">当前空间</p>
        <p className="mt-1 break-all text-sm font-medium">{spaceKey || '未选择空间'}</p>
      </div>

      {/* 切换输入 */}
      <div className="px-3 py-2 border-t border-border/40">
        <label htmlFor="space-input" className="text-xs text-muted-foreground">
          切换或新建
        </label>
        <input
          id="space-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') switchSpace()
          }}
          placeholder="输入空间名称"
          className="mt-1.5 w-full rounded-lg border bg-background/80 px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring"
        />
        <Button size="sm" onClick={switchSpace} className="mt-2 w-full gap-1.5">
          <Check className="w-3.5 h-3.5" />
          进入空间
        </Button>
      </div>

      {/* 分享 / 退出 */}
      <div className="flex items-center gap-1 p-2 border-t border-border/40">
        <Button
          size="sm"
          variant="ghost"
          onClick={shareLink}
          className="flex-1 gap-1.5 text-muted-foreground hover:text-foreground"
        >
          <Copy className="w-3.5 h-3.5" />
          分享
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            clearSpace()
            setOpen(false)
          }}
          className="flex-1 gap-1.5 text-muted-foreground hover:text-destructive"
        >
          <LogOut className="w-3.5 h-3.5" />
          退出
        </Button>
      </div>
    </div>
  )

  return (
    <div className="relative">
      <Button
        ref={triggerRef}
        variant="outline"
        size="sm"
        onClick={handleToggle}
        className="gap-2"
        aria-expanded={open}
      >
        <KeyRound className="w-4 h-4" />
        <span className="max-w-[100px] sm:max-w-[140px] truncate">{display}</span>
        <ChevronDown className="w-3 h-3" />
      </Button>
      {open && createPortal(dropdown, document.body)}
    </div>
  )
}

export function Header({ title, description, actions }: HeaderProps) {
  return (
    <header className="border-b border-border/50 glass px-4 py-4 sm:px-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between lg:items-center">
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-semibold tracking-tight break-words">
            {title}
          </h1>
          {description && (
            <p className="text-muted-foreground mt-1 text-sm sm:text-base break-words">
              {description}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <SpaceIndicator />
          {actions}
        </div>
      </div>
    </header>
  )
}

export function HeaderAction({
  icon: Icon,
  label,
  onClick,
}: {
  icon: React.ElementType
  label: string
  onClick?: () => void
}) {
  return (
    <Button onClick={onClick} className="gap-2 shrink-0" aria-label={label}>
      <Icon className="w-4 h-4 shrink-0" />
      <span className="hidden sm:inline">{label}</span>
    </Button>
  )
}
