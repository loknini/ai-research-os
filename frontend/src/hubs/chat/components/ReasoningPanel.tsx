import { ChevronRight, Loader2, Check, X } from 'lucide-react'
import { cn } from '@/utils'
import { ReasoningStep } from '../types'

export function ReasoningPanel({ steps, open, onToggle }: { steps: ReasoningStep[]; open?: boolean; onToggle?: () => void }) {
  const toolCount = steps.filter((s) => s.kind === 'tool').length
  const isControlled = open !== undefined && onToggle !== undefined
  return (
    <details open={open} className="group rounded-xl border border-border/60 bg-muted/40 overflow-hidden">
      <summary
        onClick={isControlled ? (e) => { e.preventDefault(); onToggle?.() } : undefined}
        className="flex items-center gap-2 px-3 py-2 cursor-pointer text-xs text-muted-foreground select-none hover:bg-muted/60 list-none [&::-webkit-details-marker]:hidden"
      >
        <ChevronRight className="w-3.5 h-3.5 transition-transform group-open:rotate-90" />
        <span>思考过程</span>
        {toolCount > 0 && <span className="rounded-full bg-primary/10 text-primary px-1.5 py-0.5 text-[10px] font-medium">调用 {toolCount} 个工具</span>}
      </summary>
      <div className="px-3 pb-3 space-y-2">
        {steps.map((s, i) =>
          s.kind === 'text' ? (
            <p key={i} className="text-xs text-muted-foreground/90 leading-relaxed whitespace-pre-wrap border-l-2 border-border pl-2">{s.content}</p>
          ) : (
            <div key={i} className="rounded-lg bg-background/60 px-2.5 py-2 border border-border/50">
              <div className="flex items-center gap-1.5 text-xs">
                {s.status === 'running' ? <Loader2 className="w-3 h-3 animate-spin text-primary" /> : s.status === 'success' ? <Check className="w-3 h-3 text-green-600" /> : <X className="w-3 h-3 text-red-600" />}
                <span className="font-medium">{s.name}</span>
                <span className="text-[10px] text-muted-foreground">{s.status === 'running' ? '执行中' : s.status === 'success' ? '成功' : '失败'}</span>
              </div>
              {s.params && Object.keys(s.params).length > 0 && (
                <details className="mt-1">
                  <summary className="text-[10px] text-muted-foreground/80 cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden hover:text-muted-foreground">参数</summary>
                  <pre className="mt-1 text-[10px] text-muted-foreground bg-muted/50 rounded p-1.5 overflow-x-auto whitespace-pre-wrap break-all">{JSON.stringify(s.params, null, 2)}</pre>
                </details>
              )}
              {s.message && <p className={cn('mt-1 text-[10px] leading-relaxed', s.status === 'error' ? 'text-red-600' : 'text-muted-foreground')}>{s.message}</p>}
              {s.result !== undefined && s.status !== 'running' && (
                <details className="mt-1">
                  <summary className="text-[10px] text-muted-foreground/80 cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden hover:text-muted-foreground">完整返回结果</summary>
                  <pre className="mt-1 text-[10px] text-muted-foreground bg-muted/50 rounded p-1.5 overflow-x-auto whitespace-pre-wrap break-all max-h-40">{JSON.stringify(s.result, null, 2)}</pre>
                </details>
              )}
            </div>
          )
        )}
      </div>
    </details>
  )
}
