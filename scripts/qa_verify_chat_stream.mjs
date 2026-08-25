// Regression test for the Chat Hub SSE parser bug.
// Mirrors the EXACT fixed loop in frontend/src/hubs/chat/services/chatApi.ts
// (streamChatCompletion). Feeds the user's real SSE frames and asserts the
// raw "data: ..." prefix is stripped and [DONE] is consumed (not rendered).
//
// Run: node scripts/qa_verify_chat_stream.mjs

// --- faithful copy of the fixed parser loop ---
function runParser(sseText) {
  const chunks = []
  const contexts = []
  let errorMsg = null
  let done = false

  const onChunk = (c) => chunks.push(c)
  const onToolStart = () => {}
  const onToolResult = () => {}
  const onError = (e) => { errorMsg = e }
  const onContext = (ctx) => contexts.push(ctx)

  let buffer = ''
  const lines = sseText.split('\n')
  buffer = lines.pop() || ''

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) continue

    let payload = trimmed
    if (trimmed.startsWith('data:')) {
      payload = trimmed.slice(trimmed.indexOf(':') + 1).trim()
    }
    if (!payload) continue

    if (payload === '[DONE]') { done = true; break }
    if (payload.startsWith('[ERROR]')) { onError(payload.slice(7)); break }

    try {
      const parsed = JSON.parse(payload)
      switch (parsed.type) {
        case 'text':
          if (parsed.content) onChunk(parsed.content)
          break
        case 'tool_start':
          if (parsed.tool) onToolStart(parsed.tool, parsed.parameters)
          break
        case 'tool_result':
          if (parsed.result) onToolResult(parsed.result)
          break
        case 'error':
          onError(parsed.error || 'Unknown error')
          break
        case 'context':
          if (parsed.estimated_tokens !== undefined) {
            onContext({ estimated_tokens: parsed.estimated_tokens, limit: parsed.limit, compressed: !!parsed.compressed })
          }
          break
      }
    } catch {
      if (payload) onChunk(payload)
    }
  }

  return { text: chunks.join(''), contexts, errorMsg, done, rawContainsDataPrefix: chunks.some((c) => c.startsWith('data:')) }
}

// --- build the SSE buffer exactly as the backend emits it (data: <json>\n\n) ---
const frames = [
  { type: 'context', estimated_tokens: 350, limit: 16000, compressed: false },
  { type: 'text', content: '\n\n' },
  { type: 'text', content: '你好' },
  { type: 'text', content: '！' },
  { type: 'text', content: '我是' },
  { type: 'text', content: ' Ag' },
  { type: 'text', content: 'nes' },
  { type: 'text', content: '-' },
  { type: 'text', content: '2' },
  { type: 'text', content: '0' },
  { type: 'text', content: '-' },
  { type: 'text', content: 'Flash' },
  { type: 'text', content: '，' },
  { type: 'text', content: '由' },
  { type: 'text', content: ' S' },
  { type: 'text', content: 'api' },
  { type: 'text', content: 'ens' },
  { type: 'text', content: ' AI' },
  { type: 'text', content: ' ' },
  { type: 'text', content: '开发' },
  { type: 'text', content: '。' },
]
const sse = frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join('') + 'data: [DONE]\n\n'

const result = runParser(sse)

// expected text = concatenation of every text frame's content (computed from source of truth)
const expectedText = frames.filter((f) => f.type === 'text').map((f) => f.content).join('')
const expectedClean = !result.rawContainsDataPrefix && result.done && !result.errorMsg
const contextOk =
  result.contexts.length === 1 &&
  result.contexts[0].estimated_tokens === 350 &&
  result.contexts[0].limit === 16000 &&
  result.contexts[0].compressed === false

console.log('extracted text =', JSON.stringify(result.text))
console.log('contains "data:" prefix in rendered text?', result.rawContainsDataPrefix)
console.log('[DONE] consumed (not rendered)?', result.done)
console.log('context frame parsed?', contextOk, JSON.stringify(result.contexts[0] || null))

const ok = result.text === expectedText && expectedClean && contextOk
console.log('RESULT:', ok ? 'ALL_PASS' : 'FAIL')
process.exit(ok ? 0 : 1)
