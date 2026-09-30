import { beforeEach, describe, expect, it, vi } from 'vitest'
import { openEventStream } from '@/services/api'
import { streamChatCompletion } from './chatApi'

vi.mock('@/services/api', () => ({
  apiRequest: vi.fn(),
  openEventStream: vi.fn(),
}))

describe('streamChatCompletion', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('按 SSE 协议解析跨帧文本、上下文与结束标记', async () => {
    const frames = [
      { type: 'context', estimated_tokens: 350, limit: 16000, compressed: false },
      { type: 'text', content: '\n\n' },
      { type: 'text', content: '你好！' },
      { type: 'text', content: '我是 Agnes。' },
    ]
    const payload = frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join('')
      + 'data: [DONE]\n\n'
    vi.mocked(openEventStream).mockResolvedValue(
      new Response(payload, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    )

    const chunks: string[] = []
    const contexts: Array<{ estimated_tokens: number; limit: number; compressed: boolean }> = []
    const errors: string[] = []

    await streamChatCompletion(
      [],
      (chunk) => chunks.push(chunk),
      undefined,
      undefined,
      (error) => errors.push(error),
      (context) => contexts.push(context)
    )

    expect(chunks.join('')).toBe('\n\n你好！我是 Agnes。')
    expect(chunks.some((chunk) => chunk.startsWith('data:'))).toBe(false)
    expect(chunks.join('')).not.toContain('[DONE]')
    expect(contexts).toEqual([
      { estimated_tokens: 350, limit: 16000, compressed: false },
    ])
    expect(errors).toEqual([])
  })
})
