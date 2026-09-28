import type { ChatContentPart, Message } from './types'

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
