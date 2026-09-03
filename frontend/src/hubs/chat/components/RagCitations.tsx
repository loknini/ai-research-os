import { BookOpen } from 'lucide-react'
import { cn } from '@/utils'
import { RagSource } from '../types'

export function RagCitations({ sources, openRank, onOpenRank }: { sources: RagSource[]; openRank: number | null; onOpenRank: (rank: number | null) => void }) {
  if (!sources.length) return null
  return (
    <div id="rag-citations" className="mt-3 rounded-xl border border-border/60 bg-muted/30 p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-2">
        <BookOpen className="w-3.5 h-3.5" />
        <span>引用来源（{sources.length}）</span>
        <span className="text-[10px] text-muted-foreground/70">点击角标或卡片展开片段</span>
      </div>
      <div className="space-y-1.5">
        {sources.map((s) => {
          const open = openRank === s.rank
          const pageLabel = s.pageEnd && s.pageEnd !== s.pageStart ? `第 ${s.pageStart}-${s.pageEnd} 页` : `第 ${s.pageStart} 页`
          return (
            <button
              key={s.rank}
              id={`rag-cite-${s.rank}`}
              onClick={() => onOpenRank(open ? null : s.rank)}
              className={cn('w-full text-left rounded-lg bg-background/60 border px-2.5 py-2 transition-colors', open ? 'border-primary/40 bg-primary/5' : 'border-border/50 hover:bg-background')}
            >
              <div className="flex items-center gap-2 text-xs">
                <span className="inline-flex h-4 w-4 items-center justify-center rounded bg-primary/15 text-primary text-[10px] font-semibold flex-shrink-0">{s.rank}</span>
                <span className="font-medium truncate flex-1">{s.fileName}</span>
                <span className="text-[10px] text-muted-foreground whitespace-nowrap flex-shrink-0">{pageLabel}</span>
              </div>
              {open && <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground whitespace-pre-wrap border-l-2 border-border pl-2 max-h-44 overflow-auto">{s.snippet}</p>}
            </button>
          )
        })}
      </div>
    </div>
  )
}
