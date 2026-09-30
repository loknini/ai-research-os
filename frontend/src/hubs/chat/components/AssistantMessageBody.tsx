import { useCallback, useMemo, useState } from 'react'
import { stripToolCallTrace } from '@/utils'
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
  const clean = useMemo(() => stripToolCallTrace(text), [text])
  return <MessageContent content={clean} citationSources={sources} onCitationClick={onCitationClick} />
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
