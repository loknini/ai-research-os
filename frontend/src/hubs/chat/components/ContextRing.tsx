import { cn } from '@/utils'

interface Props {
  value: number
  limit: number
  compressed: boolean
  expanded: boolean
  onToggle: () => void
}

export function ContextRing({ value, limit, compressed, expanded, onToggle }: Props) {
  const pct = Math.min(1, Math.max(0, value / (limit || 1)))
  const remaining = Math.max(0, (limit || 0) - value)
  const r = 12
  const circ = 2 * Math.PI * r
  const offset = (1 - pct) * circ
  const color =
    pct >= 0.9 ? 'stroke-red-500' : pct >= 0.7 ? 'stroke-amber-500' : 'stroke-primary'
  const pctLabel = `${Math.round(pct * 100)}%`

  return (
    <div id="context-ring" className="relative flex items-center gap-1.5">
      <button
        type="button"
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onToggle()
          }
        }}
        aria-expanded={expanded}
        aria-label={`上下文 ${value.toLocaleString()} / ${limit.toLocaleString()}，${pctLabel}，剩余 ${remaining.toLocaleString()}${compressed ? '，已压缩' : ''}`}
        className="relative flex h-7 w-7 items-center justify-center rounded-full hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        title="点击查看上下文详情"
      >
        <svg width={28} height={28} viewBox="0 0 28 28" className="-rotate-90">
          <circle cx={14} cy={14} r={r} strokeWidth={2.5} className="stroke-border/20 fill-none" />
          <circle
            cx={14}
            cy={14}
            r={r}
            strokeWidth={2.5}
            strokeLinecap="round"
            className={cn('fill-none transition-[stroke-dashoffset] duration-600 ease-out', color)}
            strokeDasharray={circ}
            strokeDashoffset={offset}
          />
        </svg>
        <span className="absolute text-[8px] font-semibold tabular-nums leading-none">{pctLabel}</span>
      </button>
      {expanded && (
        <div className="absolute right-0 top-full mt-1 z-20 w-64 rounded-lg border border-border/60 bg-popover p-3 shadow-lg text-xs space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">已用</span>
            <span className="font-medium tabular-nums">
              {value.toLocaleString()} / {limit.toLocaleString()} ({pctLabel})
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">剩余</span>
            <span className="font-medium tabular-nums">{remaining.toLocaleString()} tokens</span>
          </div>
          <div className="flex items-center gap-1.5 pt-1 border-t border-border/40">
            <span className={cn('h-2 w-2 rounded-full flex-shrink-0', compressed ? 'bg-blue-500' : 'bg-muted-foreground/40')} />
            <span className={compressed ? 'text-blue-600' : 'text-muted-foreground'}>{compressed ? '已自动压缩历史' : '未压缩'}</span>
          </div>
          <p className="text-[11px] leading-relaxed text-muted-foreground/80">
            阈值：0-70% 蓝色 / 70-90% 琥珀 / 90%+ 红色。点击圆环可收起。
          </p>
        </div>
      )}
    </div>
  )
}
