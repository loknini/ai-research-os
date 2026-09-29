import type { ChatContentPart, Conversation, Message, TokenUsage } from './types'

export function estimateTokensLocal(messages: Pick<Message, 'content'>[]): number {
  let total = 0
  for (const message of messages) {
    const content = typeof message.content === 'string'
      ? message.content
      : JSON.stringify(message.content || '')
    for (const character of content) {
      if (
        (character >= '\u4e00' && character <= '\u9fff') ||
        (character >= '\u3040' && character <= '\u30ff') ||
        (character >= '\uac00' && character <= '\ud7af')
      ) {
        total += 1
      } else if (!/\s/.test(character)) {
        total += 0.25
      }
    }
  }
  return Math.floor(total)
}

export function extractTextFromContent(content: string | ChatContentPart[]): string {
  if (typeof content === 'string') return content
  return content
    .map((part) => (part.type === 'text' ? part.text || '' : '[图片]'))
    .join('\n')
    .trim()
}

/** Remove only blank lines before an assistant reply, preserving code indentation. */
export function stripAssistantLeadingBreaks(content: string): string {
  return content.replace(/^(?:[\t ]*\r?\n)+/, '')
}

/** Append an SSE text delta without allowing providers to create an empty first line. */
export function appendAssistantDelta(current: string, delta: string): string {
  return stripAssistantLeadingBreaks(current + delta)
}

/**
 * Replace the live streaming bubble with the persisted assistant message in
 * the same React update. The subsequent detail reload still fills in branch
 * metadata, but no network-sized blank frame is exposed to the user.
 */
export function appendFinalMessage(
  conversation: Conversation | null,
  message: Message,
  conversationId: string
): Conversation | null {
  if (!conversation || conversation.id !== conversationId) return conversation
  if (conversation.messages.some((item) => item.id === message.id)) return conversation

  return {
    ...conversation,
    messages: [...conversation.messages, message],
    currentLeafId: message.id,
    updatedAt: Math.max(conversation.updatedAt, message.timestamp),
  }
}

export function addTokenUsage(
  previous: TokenUsage | undefined,
  current: TokenUsage
): TokenUsage {
  return {
    prompt_tokens: (previous?.prompt_tokens || 0) + current.prompt_tokens,
    completion_tokens: (previous?.completion_tokens || 0) + current.completion_tokens,
    total_tokens: (previous?.total_tokens || 0) + current.total_tokens,
  }
}
