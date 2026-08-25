import { Conversation, Message, ToolResult, RagSource } from '../types'

// 调用 FastAPI 后端 /api/chat/completions/stream 进行流式聊天（支持工具调用）
const streamChatCompletion = async (
  messages: Message[],
  onChunk: (chunk: string) => void,
  onToolStart?: (tool: string, params: any) => void,
  onToolResult?: (result: ToolResult) => void,
  onError?: (error: string) => void,
  onContext?: (ctx: { estimated_tokens: number; limit: number; compressed: boolean }) => void,
  signal?: AbortSignal,
  rag?: { enabled: boolean; sourceIds?: string[] },
  onRagSources?: (sources: RagSource[], mode: string) => void
): Promise<void> => {
  // 从后端 result payload 中提取可读摘要（优先 error，其次 message，再截断 results）
  const summarizeToolResult = (tool: string, raw: any): string => {
    if (!raw || typeof raw !== 'object') return String(raw ?? '')
    if (raw.error) return `${tool} 返回错误：${raw.error}`
    if (raw.message) return String(raw.message)
    if (Array.isArray(raw.results) && raw.results.length > 0) {
      return `${tool} 获取到 ${raw.results.length} 条结果`
    }
    if (raw.success === true) return `${tool} 执行成功`
    if (raw.success === false) return `${tool} 执行失败`
    return JSON.stringify(raw).slice(0, 200)
  }
  try {
    // 转换消息格式（过滤掉系统消息，后端会添加）
    const apiMessages = messages
      .filter((m) => m.role !== 'system')
      .map((m) => ({
        role: m.role,
        content: m.content,
      }))

    const response = await fetch('/api/chat/completions/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        messages: apiMessages,
        rag_enabled: rag?.enabled ?? false,
        rag_source_ids: rag?.sourceIds && rag.sourceIds.length > 0 ? rag.sourceIds : null,
      }),
      signal,
    })

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body')
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed) continue

        // SSE 协议：去掉 "data:" 前缀，否则 JSON.parse 会把整行当普通文本渲染出来
        let payload = trimmed
        if (trimmed.startsWith('data:')) {
          payload = trimmed.slice(trimmed.indexOf(':') + 1).trim()
        }
        if (!payload) continue

        // 处理 [DONE] 标记
        if (payload === '[DONE]') {
          return
        }

        // 处理 [ERROR] 标记
        if (payload.startsWith('[ERROR]')) {
          onError?.(payload.slice(7))
          return
        }

        try {
          const parsed = JSON.parse(payload)

          // 处理不同类型的消息
          switch (parsed.type) {
            case 'text':
              if (parsed.content) {
                onChunk(parsed.content)
              }
              break
            case 'tool_start':
              if (parsed.tool) {
                onToolStart?.(parsed.tool, parsed.parameters)
              }
              break
            case 'tool_result':
              if (parsed.result) {
                const tr: ToolResult = {
                  tool: parsed.tool || '',
                  success: parsed.result.success ?? false,
                  message: summarizeToolResult(parsed.tool, parsed.result),
                  result: parsed.result,
                }
                onToolResult?.(tr)
              }
              break
            case 'error':
              onError?.(parsed.error || 'Unknown error')
              return
            case 'context':
              if (parsed.estimated_tokens !== undefined) {
                onContext?.({
                  estimated_tokens: parsed.estimated_tokens,
                  limit: parsed.limit,
                  compressed: !!parsed.compressed,
                })
              }
              break
            case 'rag_sources':
              if (Array.isArray(parsed.sources)) {
                onRagSources?.(parsed.sources as RagSource[], parsed.mode || 'off')
              }
              break
          }
        } catch {
          // 不是 JSON 格式，可能是普通文本
          if (payload) {
            onChunk(payload)
          }
        }
      }
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      console.log('Chat stream aborted by user navigation')
      return
    }
    console.error('Chat stream error:', error)
    onError?.(error instanceof Error ? error.message : 'Unknown error')
  }
}

// API 函数
const fetchConversations = async (): Promise<Conversation[]> => {
  const response = await fetch('/api/conversations')
  const data = await response.json()
  if (data.success) {
    return data.conversations.map((c: any) => ({
      ...c,
      messages: [] // 列表中不包含消息详情
    }))
  }
  return []
}

const fetchConversationDetail = async (id: string): Promise<Conversation | null> => {
  const response = await fetch(`/api/conversations/${id}`)
  const data = await response.json()
  if (data.success && data.conversation) {
    return {
      ...data.conversation,
      currentLeafId: data.conversation.currentLeafId ?? null,
      messages: data.conversation.messages.map((m: any) => ({
        ...m,
        parentId: m.parentId ?? null,
        siblingCount: m.siblingCount ?? 1,
        siblingIndex: m.siblingIndex ?? 0,
        siblingIds: m.siblingIds ?? [],
        metadata: m.metadata || {}
      }))
    }
  }
  return null
}

const createConversationAPI = async (conversation: Conversation): Promise<Conversation | null> => {
  const response = await fetch('/api/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(conversation)
  })
  const data = await response.json()
  if (data.success && data.conversation) {
    return {
      ...data.conversation,
      currentLeafId: data.conversation.currentLeafId ?? null,
      messages: data.conversation.messages.map((m: any) => ({
        ...m,
        parentId: m.parentId ?? null,
        siblingCount: m.siblingCount ?? 1,
        siblingIndex: m.siblingIndex ?? 0,
        siblingIds: m.siblingIds ?? [],
        metadata: m.metadata || {}
      }))
    }
  }
  return null
}

const updateConversationAPI = async (id: string, updates: Partial<Conversation>): Promise<boolean> => {
  const response = await fetch(`/api/conversations/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates)
  })
  const data = await response.json()
  return data.success
}

const deleteConversationAPI = async (id: string): Promise<boolean> => {
  const response = await fetch(`/api/conversations/${id}`, {
    method: 'DELETE'
  })
  const data = await response.json()
  return data.success
}

const addMessageAPI = async (conversationId: string, message: Message): Promise<boolean> => {
  const response = await fetch(`/api/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      id: message.id,
      role: message.role,
      content: message.content,
      timestamp: message.timestamp,
      metadata: message.metadata || {},
      parentId: message.parentId ?? null,
    })
  })
  const data = await response.json()
  return data.success
}

const updateMessageAPI = async (conversationId: string, messageId: string, content: string): Promise<boolean> => {
  const response = await fetch(`/api/conversations/${conversationId}/messages/${messageId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content })
  })
  const data = await response.json()
  return data.success
}

const deleteMessagesAfterAPI = async (conversationId: string, messageId: string): Promise<boolean> => {
  const response = await fetch(`/api/conversations/${conversationId}/messages/delete-after`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messageId })
  })
  const data = await response.json()
  return data.success
}

const switchBranchAPI = async (conversationId: string, messageId: string): Promise<Conversation | null> => {
  const response = await fetch(`/api/conversations/${conversationId}/switch-branch/${messageId}`, {
    method: 'POST',
  })
  const data = await response.json()
  if (data.success && data.conversation) {
    return {
      ...data.conversation,
      currentLeafId: data.conversation.currentLeafId ?? null,
      messages: data.conversation.messages.map((m: any) => ({
        ...m,
        parentId: m.parentId ?? null,
        siblingCount: m.siblingCount ?? 1,
        siblingIndex: m.siblingIndex ?? 0,
        siblingIds: m.siblingIds ?? [],
        metadata: m.metadata || {}
      }))
    }
  }
  return null
}

export {
  streamChatCompletion,
  fetchConversations,
  fetchConversationDetail,
  createConversationAPI,
  updateConversationAPI,
  deleteConversationAPI,
  addMessageAPI,
  updateMessageAPI,
  deleteMessagesAfterAPI,
  switchBranchAPI,
}
