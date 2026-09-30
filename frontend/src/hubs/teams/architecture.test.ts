import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..')

function read(relativePath: string): string {
  return fs.readFileSync(path.join(repositoryRoot, relativePath), 'utf8')
}

describe('专家团队前端架构契约', () => {
  const app = read('frontend/src/App.tsx')
  const navigation = read('frontend/src/config/navigation.ts')
  const teams = read('frontend/src/hubs/teams/index.tsx')
  const workflow = read('frontend/src/components/agent/agent-workflow.tsx')
  const contextDialog = read('frontend/src/components/agent/team-context-run-dialog.tsx')
  const software = read('frontend/src/hubs/software/components/IdeaFormDialog.tsx')
  const papers = read('frontend/src/hubs/paper/PaperHub.tsx')
  const knowledge = read('frontend/src/hubs/knowledge/KnowledgeHub.tsx')
  const development = read('frontend/src/hubs/software/components/DevelopmentWorkspace.tsx')
  const projectApi = read('frontend/src/hubs/software/services/projectsApi.ts')
  const floatingChat = read('frontend/src/components/chat/chat-panel.tsx')
  const chatController = read('frontend/src/hubs/chat/hooks/useChatController.ts')
  const packageJson = JSON.parse(read('frontend/package.json')) as {
    dependencies: Record<string, string>
  }

  const contracts: Array<[string, boolean]> = [
    ['注册独立一级路由', app.includes('path="/teams"') && app.includes('@/hubs/teams')],
    ['导航包含专家团队', navigation.includes("path: '/teams'") && navigation.includes("name: '专家团队'")],
    ['React Flow 是运行时依赖', Boolean(packageJson.dependencies['@xyflow/react'])],
    ['编排器支持拖拽与连线', teams.includes('<ReactFlow') && teams.includes('onConnect={readOnly ? undefined : onConnect}') && teams.includes('screenToFlowPosition')],
    ['团队支持导入导出', teams.includes("'/api/agent/teams/import'") && teams.includes('/export')],
    ['边序列化保留画布顺序', !teams.includes('nodes: changed.map') && teams.includes('edges: changed.map')],
    ['团队策略可编辑', teams.includes('allowedTools') && teams.includes('maxConcurrency') && teams.includes('approvalMode')],
    ['角色模板支持新建编辑', teams.includes('RoleTemplateEditor') && teams.includes("method = role.id ? 'PUT' : 'POST'")],
    ['内置团队提供只读视图', teams.includes('readOnly={editorReadOnly}') && teams.includes('内置团队 · 只读') && teams.includes('<Eye className="mr-1 h-4 w-4" />查看')],
    ['内置角色提供只读视图', teams.includes('readOnly={roleReadOnly}') && teams.includes('这是内置只读模板；你可以查看完整配置')],
    ['节点模型支持选择与手输', teams.includes("'/api/settings/llm/models'") && teams.includes('<datalist')],
    ['Schema 草稿在保存时校验', teams.includes('schemaDrafts') && teams.includes('不是合法 JSON')],
    ['AgentWorkflow 保留团队上下文契约', workflow.includes('teamId?: string') && workflow.includes('context?: {') && workflow.includes('primaryOutput')],
    ['DAG 失败不会误报完成', workflow.includes("case 'run_failed'") && workflow.includes('!failedRef.current')],
    ['试运行映射节点状态', teams.includes('runNodeStatuses') && teams.includes('onEvent={handleRunEvent}')],
    ['团队卡片提供场景入口', teams.includes('去使用') && teams.includes('software_project') && teams.includes('CONTEXT_LABELS')],
    ['深链覆盖三个 Hub', teams.includes('action=develop') && teams.includes('action=expert-review') && teams.includes('action=knowledge-synthesis')],
    ['软件 Hub 使用默认团队', software.includes('builtin-software-planning') && software.includes("kind: 'software_idea'")],
    ['软件 Hub 移除旧结果字段', !software.includes('architectOutput') && !software.includes('plannerOutput')],
    ['软件结果先预览再应用', software.includes('项目草案预览') && software.includes('应用到项目')],
    ['论文 Hub 显式保存结果', papers.includes('builtin-paper-review') && papers.includes('保存为 AI 笔记')],
    ['知识 Hub 显式保存结果', knowledge.includes('builtin-knowledge-synthesis') && knowledge.includes('保存为新的 AI 笔记')],
    ['上下文限制二十个实体', contextDialog.includes('entityIds: ids') && contextDialog.includes('slice(0, 20)')],
    ['上下文对话框显式应用', contextDialog.includes('结果预览') && contextDialog.includes('onApply(output, ids)')],
    ['研发运行显式应用', projectApi.includes('/development-runs') && development.includes('审阅无误，应用到项目')],
    ['研发运行展示授权边界', development.includes('workspaceWrites') && development.includes('verificationCommands')],
    ['浮动助手复用 Chat 流程', floatingChat.includes('chatGenerationManager.start') && floatingChat.includes('createConversationAPI')],
    ['旧关键词助手已删除', !floatingChat.includes('useAIAgent') && !fs.existsSync(path.join(repositoryRoot, 'frontend/src/services/aiAgent.ts'))],
    ['首次发送创建会话并启动生成', chatController.includes('let targetId = currentConversationId') && chatController.includes('chatGenerationManager.start(updatedMessages, targetId')],
  ]

  it.each(contracts)('%s', (_label, satisfied) => {
    expect(satisfied).toBe(true)
  })
})
