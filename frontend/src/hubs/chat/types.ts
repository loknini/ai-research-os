// 工具调用类型
interface ToolCall {
  name: string
  parameters: Record<string, any>
}

// 工具执行结果（后端 tool_result 事件的完整 payload）
interface ToolResult {
  tool: string
  success: boolean
  message?: string
  result?: any
}

// 思考过程步骤（用于可折叠的「思考过程」面板）
// - text：模型在工具调用之间输出的思考/中间说明
// - tool：一次工具调用的名称、参数与结果（含完整工具返回 payload）
type ReasoningStep =
  | { kind: 'text'; content: string }
  | {
      kind: 'tool'
      name: string
      params?: Record<string, any>
      status: 'running' | 'success' | 'error'
      message?: string
      success?: boolean
      result?: any
    }

// 多模态消息内容片段（文本 + 图片，用于多模态大模型对话输入）
interface ChatContentPart {
  type: 'text' | 'image_url'
  text?: string                  // type==='text' 时的文本
  image_url?: { url: string }    // type==='image_url' 时的图片地址（data URI 或 URL）
}

// 消息类型
interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string | ChatContentPart[]
  timestamp: number
  isStreaming?: boolean
  metadata?: Record<string, any>
  toolCalls?: ToolCall[]
  toolResults?: ToolResult[]
  parentId?: string | null        // 父消息 id（分叉树）
  siblingCount?: number           // 同级兄弟数（用于分支导航）
  siblingIndex?: number           // 当前在兄弟列表中的索引
  siblingIds?: string[]           // 所有兄弟消息 id
  ragSources?: RagSource[]        // RAG 接地回答引用的文档片段（溯源卡片）
}

// RAG 引用溯源来源（来自聊天后端检索注入，前端渲染出处卡片）
interface RagSource {
  rank: number
  fileName: string
  filePath: string
  fileType: string
  pageStart: number
  pageEnd: number
  snippet: string
  score: number
}

// 会话类型
interface Conversation {
  id: string
  title: string
  messages: Message[]
  createdAt: number
  updatedAt: number
  currentLeafId?: string | null   // 当前分支叶子消息 id
  metadata?: Record<string, any>  // 会话级配置（如 RAG 接地开关 / 来源筛选），按会话持久化
}

export type { ToolCall, ToolResult, Message, Conversation, ReasoningStep, RagSource, ChatContentPart }
