/**
 * Extracted state hook for ChatHub — first step of >600-lines split (T6).
 * Wraps conversation load + RAG toggle so ChatHub.tsx can be thinned incrementally.
 * Full split (sidebar/message-list/input) tracked in TECH-DEBT.md:T6 follow-up.
 */
import { useCallback, useState } from 'react'
import { Conversation } from '../types'
import { fetchConversations, fetchConversationDetail } from '../services/chatApi'

export function useChatState() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [isLoading, setIsLoading] = useState(true)

  const loadConversations = useCallback(async () => {
    setIsLoading(true)
    try {
      const list = await fetchConversations()
      setConversations(list)
      return list
    } finally {
      setIsLoading(false)
    }
  }, [])

  const loadDetail = useCallback(async (id: string) => {
    return fetchConversationDetail(id)
  }, [])

  return { conversations, setConversations, isLoading, loadConversations, loadDetail }
}
