import { cn } from '@/utils'
import type { TokenUsage } from '../types'

interface Props {
  value: number
  limit: number
  compressed: boolean
  lastUsage?: TokenUsage
  cumulativeUsage?: TokenUsage
  expanded: boolean
  onToggle: () => void
}

export function ContextRing({
  value,
  limit,
  compressed,
  lastUsage,
  cumulativeUsage,
  expanded,
  onToggle,
}: Props) {
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
        aria-label={`当前上下文估算 ${value.toLocaleString()} / ${limit.toLocaleString()}，${pctLabel}，剩余 ${remaining.toLocaleString()}${compressed ? '，已压缩' : ''}`}
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
        <div className="absolute right-0 top-full mt-1 z-20 w-72 rounded-lg border border-border/60 bg-popover p-3 shadow-lg text-xs space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">当前上下文（估算）</span>
            <span className="font-medium tabular-nums">
              {value.toLocaleString()} / {limit.toLocaleString()} ({pctLabel})
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">剩余</span>
            <span className="font-medium tabular-nums">{remaining.toLocaleString()} tokens</span>
          </div>
          <div className="flex items-start justify-between gap-3 pt-1 border-t border-border/40">
            <span className="text-muted-foreground">本轮实际</span>
            {lastUsage ? (
              <span className="text-right font-medium tabular-nums">
                {lastUsage.total_tokens.toLocaleString()} tokens
                <span className="block font-normal text-[10px] text-muted-foreground">
                  输入 {lastUsage.prompt_tokens.toLocaleString()} / 输出 {lastUsage.completion_tokens.toLocaleString()}
                </span>
              </span>
            ) : (
              <span className="text-muted-foreground">供应商未返回</span>
            )}
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">会话累计实际</span>
            <span className="font-medium tabular-nums">
              {cumulativeUsage
                ? `${cumulativeUsage.total_tokens.toLocaleString()} tokens`
                : '暂不可用'}
            </span>
          </div>
          <div className="flex items-center gap-1.5 pt-1 border-t border-border/40">
            <span className={cn('h-2 w-2 rounded-full flex-shrink-0', compressed ? 'bg-blue-500' : 'bg-muted-foreground/40')} />
            <span className={compressed ? 'text-blue-600' : 'text-muted-foreground'}>{compressed ? '已自动压缩历史' : '未压缩'}</span>
          </div>
        </div>
      )}
    </div>
  )
}
