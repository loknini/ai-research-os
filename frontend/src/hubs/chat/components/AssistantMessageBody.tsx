import { useCallback, useMemo, useState } from 'react'
import { Wrench } from 'lucide-react'
import { sanitizeToolCallTrace } from '@/utils'
import type { ChatContentPart, RagSource, ReasoningStep } from '../types'
import MessageContent from './MessageContent'
import { RagCitations } from './RagCitations'
import { ReasoningPanel } from './ReasoningPanel'
import { extractTextFromContent } from '../messageUtils'

function AssistantContent({
  content,
  sources,
  onCitationClick,
}: {
  content: string | ChatContentPart[]
  sources?: RagSource[]
  onCitationClick?: (rank: number) => void
}) {
  const text = typeof content === 'string' ? content : extractTextFromContent(content)
  const { clean, trace } = useMemo(() => sanitizeToolCallTrace(text), [text])
  return (
    <>
      <MessageContent content={clean} citationSources={sources} onCitationClick={onCitationClick} />
      {trace && (
        <details className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/5 overflow-hidden">
          <summary className="flex items-center gap-1.5 px-3 py-2 cursor-pointer text-xs text-amber-700 select-none list-none [&::-webkit-details-marker]:hidden">
            <Wrench className="w-3.5 h-3.5" />
            模型原始工具调用痕迹（调试）
            <span className="text-[10px] text-amber-600/70">点击展开</span>
          </summary>
          <pre className="px-3 pb-3 text-[11px] text-muted-foreground whitespace-pre-wrap break-all max-h-60 overflow-auto">
            {trace}
          </pre>
        </details>
      )}
    </>
  )
}

export function AssistantMessageBody({
  content,
  reasoning,
  sources,
}: {
  content: string | ChatContentPart[]
  reasoning?: ReasoningStep[]
  sources?: RagSource[]
}) {
  const [openRank, setOpenRank] = useState<number | null>(null)
  const handleCitationClick = useCallback((rank: number) => {
    setOpenRank((previous) => (previous === rank ? null : rank))
    setTimeout(() => {
      document.getElementById(`rag-cite-${rank}`)?.scrollIntoView({
        behavior: 'smooth',
        block: 'nearest',
      })
    }, 60)
  }, [])

  return (
    <>
      {reasoning && reasoning.length > 0 && <ReasoningPanel steps={reasoning} />}
      <AssistantContent
        content={content}
        sources={sources}
        onCitationClick={sources?.length ? handleCitationClick : undefined}
      />
      {sources && sources.length > 0 && (
        <RagCitations sources={sources} openRank={openRank} onOpenRank={setOpenRank} />
      )}
    </>
  )
}
