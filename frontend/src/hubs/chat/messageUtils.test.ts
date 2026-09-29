import { describe, expect, it } from 'vitest'
import {
  appendAssistantDelta,
  appendFinalMessage,
  addTokenUsage,
  stripAssistantLeadingBreaks,
} from './messageUtils'
import type { Conversation, Message } from './types'

describe('assistant reply whitespace normalization', () => {
  it('removes provider-added blank lines at the beginning', () => {
    expect(stripAssistantLeadingBreaks('\n\n你好')).toBe('你好')
    expect(stripAssistantLeadingBreaks('  \r\n\r\n你好')).toBe('你好')
  })

  it('preserves meaningful indentation when no leading line break exists', () => {
    expect(stripAssistantLeadingBreaks('    indented code')).toBe('    indented code')
  })

  it('normalizes multiple leading-only stream chunks', () => {
    let content = appendAssistantDelta('', '  \n')
    content = appendAssistantDelta(content, '\n')
    content = appendAssistantDelta(content, '回答')
    expect(content).toBe('回答')
  })
})

describe('completed generation handoff', () => {
  const conversation: Conversation = {
    id: 'conversation-1',
    title: 'Test',
    messages: [],
    createdAt: 10,
    updatedAt: 10,
  }
  const finalMessage: Message = {
    id: 'assistant-1',
    role: 'assistant',
    content: '完整回答',
    timestamp: 20,
    parentId: 'user-1',
  }

  it('adds the persisted final message before the live bubble is removed', () => {
    const result = appendFinalMessage(conversation, finalMessage, conversation.id)

    expect(result?.messages).toEqual([finalMessage])
    expect(result?.currentLeafId).toBe(finalMessage.id)
    expect(result?.updatedAt).toBe(finalMessage.timestamp)
  })

  it('does not duplicate a message or write into a different conversation', () => {
    const withMessage = appendFinalMessage(conversation, finalMessage, conversation.id)!

    expect(appendFinalMessage(withMessage, finalMessage, conversation.id)).toBe(withMessage)
    expect(appendFinalMessage(conversation, finalMessage, 'conversation-2')).toBe(conversation)
  })
})

describe('token usage accounting', () => {
  it('accumulates exact provider usage across turns', () => {
    expect(addTokenUsage(
      { prompt_tokens: 100, completion_tokens: 20, total_tokens: 120 },
      { prompt_tokens: 200, completion_tokens: 30, total_tokens: 230 }
    )).toEqual({ prompt_tokens: 300, completion_tokens: 50, total_tokens: 350 })
  })
})
