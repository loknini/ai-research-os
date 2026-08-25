import type { ElementType } from 'react'
import { Sun, Moon, Monitor } from 'lucide-react'
import { useThemeStore, type ThemeMode } from '@/stores/themeStore'
import { cn } from '@/utils'

const OPTIONS: { mode: ThemeMode; icon: ElementType; label: string }[] = [
  { mode: 'light', icon: Sun, label: '浅色' },
  { mode: 'dark', icon: Moon, label: '深色' },
  { mode: 'system', icon: Monitor, label: '跟随系统' },
]

/**
 * 主题切换控件，支持两种形态：
 * - 展开侧栏：三段式 segmented control（浅 / 深 / 跟随系统）
 * - 折叠侧栏：单个图标按钮，点击在三种模式间循环
 */
export function ThemeToggle({ collapsed = false }: { collapsed?: boolean }) {
  const mode = useThemeStore((s) => s.mode)
  const setMode = useThemeStore((s) => s.setMode)

  if (collapsed) {
    const current = OPTIONS.find((o) => o.mode === mode) ?? OPTIONS[0]
    const Icon = current.icon
    return (
      <button
        type="button"
        onClick={() => {
          const idx = OPTIONS.findIndex((o) => o.mode === mode)
          setMode(OPTIONS[(idx + 1) % OPTIONS.length].mode)
        }}
        className="h-8 w-8 rounded-lg flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
        title={`主题：${current.label}（点击切换）`}
        aria-label="切换主题"
      >
        <Icon className="w-5 h-5" />
      </button>
    )
  }

  return (
    <div className="flex items-center gap-1 rounded-xl bg-muted p-1" role="group" aria-label="主题模式">
      {OPTIONS.map((o) => {
        const Icon = o.icon
        const active = o.mode === mode
        return (
          <button
            key={o.mode}
            type="button"
            onClick={() => setMode(o.mode)}
            className={cn(
              'flex-1 flex items-center justify-center rounded-lg h-7 transition-colors',
              active
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
            title={o.label}
            aria-label={o.label}
            aria-pressed={active}
          >
            <Icon className="w-4 h-4" />
          </button>
        )
      })}
    </div>
  )
}
