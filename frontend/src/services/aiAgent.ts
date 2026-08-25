/**
 * AI Agent 服务
 * 封装所有AI相关的操作和工具调用
 */

import { useChatStore } from '@/stores/appStore'
import type { ChatMessage } from '@/types'
import { generateId } from '@/utils'

// AI 工具类型
export interface AITool {
  name: string
  description: string
  parameters: Record<string, {
    type: string
    description: string
    required?: boolean
  }>
  execute: (params: Record<string, any>) => Promise<any>
}

// AI Agent 类
export class AIAgent {
  private tools: Map<string, AITool> = new Map()
  
  constructor() {
    this.registerDefaultTools()
  }
  
  // 注册默认工具
  private registerDefaultTools() {
    // 论文相关工具
    this.registerTool({
      name: 'fetch_papers',
      description: '从 arXiv 抓取论文',
      parameters: {
        keywords: { type: 'string', description: '搜索关键词', required: false },
        max_results: { type: 'number', description: '最大结果数', required: false }
      },
      execute: async (params) => {
        const response = await fetch(`/api/papers/fetch?max=${params.max_results || 10}${params.keywords ? `&keywords=${encodeURIComponent(params.keywords)}` : ''}`, {
          method: 'POST'
        })
        return await response.json()
      }
    })
    
    this.registerTool({
      name: 'summarize_paper',
      description: '总结论文内容',
      parameters: {
        paper_id: { type: 'string', description: '论文ID', required: true }
      },
      execute: async (params) => {
        const response = await fetch(`/api/papers/${params.paper_id}/summarize`, {
          method: 'POST'
        })
        return await response.json()
      }
    })
    
    this.registerTool({
      name: 'list_papers',
      description: '获取论文列表',
      parameters: {
        limit: { type: 'number', description: '数量限制', required: false }
      },
      execute: async (params) => {
        const response = await fetch(`/api/papers?limit=${params.limit || 100}`)
        return await response.json()
      }
    })
    
    // 任务相关工具
    this.registerTool({
      name: 'create_task',
      description: '创建新任务',
      parameters: {
        title: { type: 'string', description: '任务标题', required: true },
        description: { type: 'string', description: '任务描述', required: false },
        priority: { type: 'string', description: '优先级 (low/medium/high/urgent)', required: false },
        deadline: { type: 'string', description: '截止日期 (ISO格式)', required: false }
      },
      execute: async (params) => {
        const response = await fetch('/api/tasks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: params.title,
            description: params.description,
            priority: params.priority || 'medium',
            status: 'todo',
            tags: []
          })
        })
        return await response.json()
      }
    })
    
    this.registerTool({
      name: 'list_tasks',
      description: '获取任务列表',
      parameters: {
        status: { type: 'string', description: '任务状态过滤', required: false }
      },
      execute: async (params) => {
        const url = params.status ? `/api/tasks?status=${params.status}` : '/api/tasks'
        const response = await fetch(url)
        return await response.json()
      }
    })
    
    // 项目相关工具
    this.registerTool({
      name: 'create_project',
      description: '创建软件项目',
      parameters: {
        name: { type: 'string', description: '项目名称', required: true },
        description: { type: 'string', description: '项目描述', required: false },
        tech_stack: { type: 'array', description: '技术栈', required: false }
      },
      execute: async (params) => {
        const response = await fetch('/api/projects', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: params.name,
            description: params.description,
            techStack: params.tech_stack || [],
            status: 'design'
          })
        })
        return await response.json()
      }
    })
    
    // 知识库工具
    this.registerTool({
      name: 'create_note',
      description: '创建知识笔记',
      parameters: {
        title: { type: 'string', description: '笔记标题', required: true },
        content: { type: 'string', description: '笔记内容', required: true },
        type: { type: 'string', description: '笔记类型 (note/idea/summary/code)', required: false }
      },
      execute: async (params) => {
        const response = await fetch('/api/notes', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: params.title,
            content: params.content,
            type: params.type || 'note',
            tags: []
          })
        })
        return await response.json()
      }
    })
    
    // SwanLab 工具
    this.registerTool({
      name: 'fetch_swanlab_data',
      description: '从 SwanLab 获取实验数据',
      parameters: {},
      execute: async () => {
        const response = await fetch('/api/swanlab/fetch', {
          method: 'POST'
        })
        return await response.json()
      }
    })
    
    this.registerTool({
      name: 'list_experiments',
      description: '获取实验列表',
      parameters: {
        project: { type: 'string', description: '项目名称', required: false }
      },
      execute: async (params) => {
        const url = params.project 
          ? `/api/swanlab/experiments?project=${encodeURIComponent(params.project)}`
          : '/api/swanlab/cache'
        const response = await fetch(url)
        return await response.json()
      }
    })
  }
  
  // 注册工具
  registerTool(tool: AITool) {
    this.tools.set(tool.name, tool)
  }
  
  // 获取工具列表
  getTools(): AITool[] {
    return Array.from(this.tools.values())
  }
  
  // 执行工具
  async executeTool(name: string, params: Record<string, any>): Promise<any> {
    const tool = this.tools.get(name)
    if (!tool) {
      throw new Error(`Tool not found: ${name}`)
    }
    return await tool.execute(params)
  }
  
  // 解析用户意图
  parseIntent(message: string): { tool?: string; params: Record<string, any>; confidence: number } {
    const lowerMsg = message.toLowerCase()
    
    // 论文相关
    if (lowerMsg.includes('抓取') && lowerMsg.includes('论文')) {
      const keywords = message.match(/关键词[是为:]?\s*([^，。]+)/)?.[1]
      return {
        tool: 'fetch_papers',
        params: { keywords },
        confidence: 0.9
      }
    }
    
    if (lowerMsg.includes('总结') && lowerMsg.includes('论文')) {
      return { tool: 'summarize_paper', params: {}, confidence: 0.8 }
    }
    
    if (lowerMsg.includes('论文') && (lowerMsg.includes('列表') || lowerMsg.includes('查看'))) {
      return { tool: 'list_papers', params: {}, confidence: 0.8 }
    }
    
    // 任务相关
    if (lowerMsg.includes('创建') && lowerMsg.includes('任务')) {
      const title = message.match(/任务[是为:]?\s*([^，。]+)/)?.[1] || message
      return {
        tool: 'create_task',
        params: { title },
        confidence: 0.8
      }
    }
    
    if (lowerMsg.includes('任务') && (lowerMsg.includes('列表') || lowerMsg.includes('查看'))) {
      return { tool: 'list_tasks', params: {}, confidence: 0.8 }
    }
    
    // 项目相关
    if (lowerMsg.includes('创建') && lowerMsg.includes('项目')) {
      const name = message.match(/项目[是为:]?\s*([^，。]+)/)?.[1] || message
      return {
        tool: 'create_project',
        params: { name },
        confidence: 0.7
      }
    }
    
    // 实验相关
    if (lowerMsg.includes('swanlab') || lowerMsg.includes('实验')) {
      if (lowerMsg.includes('获取') || lowerMsg.includes('同步') || lowerMsg.includes('更新')) {
        return { tool: 'fetch_swanlab_data', params: {}, confidence: 0.9 }
      }
      return { tool: 'list_experiments', params: {}, confidence: 0.8 }
    }
    
    // 知识库相关
    if (lowerMsg.includes('创建') && lowerMsg.includes('笔记')) {
      return { tool: 'create_note', params: {}, confidence: 0.7 }
    }
    
    return { params: {}, confidence: 0 }
  }
  
  // 生成系统提示词
  generateSystemPrompt(): string {
    const tools = this.getTools()
    const toolDescriptions = tools.map(t => 
      `- ${t.name}: ${t.description}\n  参数: ${Object.entries(t.parameters).map(([k, v]) => `${k}(${v.type}${v.required ? ', required' : ''})`).join(', ')}`
    ).join('\n')
    
    return `你是 AI Research OS 的智能助手，可以帮助用户管理研究论文、任务、项目和实验。

可用工具：
${toolDescriptions}

你可以：
1. 从 arXiv 抓取和总结论文
2. 创建和管理任务
3. 创建软件项目
4. 管理知识笔记
5. 从 SwanLab 获取实验数据

请根据用户的问题，选择合适的工具来帮助用户。如果用户的问题不明确，请询问更多信息。`
  }
}

// 单例实例
let agentInstance: AIAgent | null = null

export function getAIAgent(): AIAgent {
  if (!agentInstance) {
    agentInstance = new AIAgent()
  }
  return agentInstance
}

// Hook 用于在组件中使用
export function useAIAgent() {
  const agent = getAIAgent()
  const { addMessage, setProcessing } = useChatStore()
  
  const sendMessage = async (content: string) => {
    // 添加用户消息
    const userMessage: ChatMessage = {
      id: generateId(),
      role: 'user',
      content,
      timestamp: Date.now()
    }
    addMessage(userMessage)
    setProcessing(true)
    
    try {
      // 解析意图
      const intent = agent.parseIntent(content)
      
      // 如果有高置信度的工具调用
      if (intent.tool && intent.confidence > 0.7) {
        // 执行工具
        const result = await agent.executeTool(intent.tool, intent.params)
        
        // 生成响应
        let responseContent = ''
        if (result.success) {
          switch (intent.tool) {
            case 'fetch_papers':
              responseContent = `成功抓取 ${result.papers?.length || 0} 篇新论文！`
              break
            case 'summarize_paper':
              responseContent = `论文总结完成：\n${result.summary || '已完成总结'}`
              break
            case 'create_task':
              responseContent = `任务「${intent.params.title}」已创建成功！`
              break
            case 'create_project':
              responseContent = `项目「${intent.params.name}」已创建成功！`
              break
            case 'fetch_swanlab_data':
              responseContent = `已从 SwanLab 获取 ${result.data?.experiments?.length || 0} 个实验数据！`
              break
            default:
              responseContent = `操作成功完成！`
          }
        } else {
          responseContent = `操作失败：${result.error || result.message || '未知错误'}`
        }
        
        const assistantMessage: ChatMessage = {
          id: generateId(),
          role: 'assistant',
          content: responseContent,
          timestamp: Date.now(),
          metadata: {
            toolCalls: [intent.tool],
            result
          }
        }
        addMessage(assistantMessage)
      } else {
        // 未匹配到内置工具：旧 /api/agent/run 端点已移除，复杂任务请到「Agent」面板处理
        const assistantMessage: ChatMessage = {
          id: generateId(),
          role: 'assistant',
          content: '这个问题超出了内置工具的能力范围。你可以到「Agent」面板，用多角色管线来处理更复杂的任务。',
          timestamp: Date.now()
        }
        addMessage(assistantMessage)
      }
    } catch (error) {
      console.error('AI Agent error:', error)
      const errorMessage: ChatMessage = {
        id: generateId(),
        role: 'assistant',
        content: '抱歉，处理您的请求时出错了。请稍后重试。',
        timestamp: Date.now()
      }
      addMessage(errorMessage)
    } finally {
      setProcessing(false)
    }
  }
  
  return {
    agent,
    sendMessage,
    executeTool: agent.executeTool.bind(agent),
    parseIntent: agent.parseIntent.bind(agent)
  }
}
