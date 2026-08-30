#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(.:)/, '$1')), '..')
let passed = 0
let failed = 0

function read(relative) {
  return fs.readFileSync(path.join(root, relative), 'utf8')
}

function check(condition, label) {
  if (condition) {
    passed += 1
    console.log(`[PASS] ${label}`)
  } else {
    failed += 1
    console.error(`[FAIL] ${label}`)
  }
}

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
const chatHub = read('frontend/src/hubs/chat/ChatHub.tsx')
const packageJson = JSON.parse(read('frontend/package.json'))

check(app.includes("path=\"/teams\"") && app.includes("@/hubs/teams"), '专家团队注册为独立一级路由')
check(navigation.includes("path: '/teams'") && navigation.includes("name: '专家团队'"), '研究分组包含专家团队导航')
check(Boolean(packageJson.dependencies['@xyflow/react']), '@xyflow/react 为正式运行依赖')
check(teams.includes('<ReactFlow') && teams.includes('onConnect={readOnly ? undefined : onConnect}') && teams.includes('screenToFlowPosition'), '编排器支持拖拽节点与可视连线')
check(teams.includes("'/api/agent/teams/import'") && teams.includes('/export'), '团队中心提供 JSON 导入与导出')
check(teams.includes('nodes: changed.map') === false && teams.includes('edges: changed.map'), '边序列化保留画布数组顺序')
check(teams.includes('allowedTools') && teams.includes('maxConcurrency') && teams.includes('approvalMode'), '节点工具与团队并发/审批配置可编辑')
check(teams.includes('RoleTemplateEditor') && teams.includes("method = role.id ? 'PUT' : 'POST'"), '角色模板管理支持新建与编辑')
check(teams.includes('readOnly={editorReadOnly}') && teams.includes('内置团队 · 只读') && teams.includes('<Eye className="mr-1 h-4 w-4" />查看'), '内置团队提供完整只读 DAG 查看入口')
check(teams.includes('readOnly={roleReadOnly}') && teams.includes('这是内置只读模板；你可以查看完整配置'), '内置角色模板提供完整只读查看入口')
check(teams.includes("'/api/settings/llm/models'") && teams.includes('<datalist'), '节点模型可从现有接口读取且允许手工输入')
check(teams.includes('schemaDrafts') && teams.includes('不是合法 JSON'), 'JSON Schema 编辑保留未完成草稿并在保存时校验')
check(workflow.includes('teamId?: string') && workflow.includes('context?: {') && workflow.includes('primaryOutput'), 'AgentWorkflow 支持 teamId/context/primaryOutput 契约')
check(workflow.includes("case 'run_failed'") && workflow.includes('!failedRef.current'), 'DAG 失败不会被前端误报为完成或应用结果')
check(teams.includes('runNodeStatuses') && teams.includes('onEvent={handleRunEvent}'), '团队试运行在原 DAG 上实时映射节点状态')
check(teams.includes('去使用') && teams.includes('software_project') && teams.includes('CONTEXT_LABELS'), '团队卡片提供中文场景与明确去使用入口')
check(teams.includes("action=develop") && teams.includes("action=expert-review") && teams.includes("action=knowledge-synthesis"), '团队用途深链覆盖软件、论文与知识 Hub')
check(software.includes('builtin-software-planning') && software.includes("kind: 'software_idea'"), '软件 Hub 使用兼容 software_idea 的默认团队')
check(!software.includes('architectOutput') && !software.includes('plannerOutput'), '软件 Hub 已移除错误的旧结果字段映射')
check(software.includes('项目草案预览') && software.includes('应用到项目'), '软件结果先预览再显式应用')
check(papers.includes('builtin-paper-review') && papers.includes('保存为 AI 笔记'), '论文 Hub 支持团队研读与显式保存')
check(knowledge.includes('builtin-knowledge-synthesis') && knowledge.includes('保存为新的 AI 笔记'), '知识 Hub 支持多笔记综合与显式保存')
check(contextDialog.includes('entityIds: ids') && contextDialog.includes('slice(0, 20)'), 'Hub 上下文只提交最多 20 个实体 ID')
check(contextDialog.includes('结果预览') && contextDialog.includes('onApply(output, ids)'), '通用上下文对话框不会自动应用结果')
check(projectApi.includes('/development-runs') && development.includes('审阅无误，应用到项目'), '软件 Hub 提供真实研发运行与显式应用界面')
check(development.includes('workspaceWrites') && development.includes('verificationCommands'), '研发运行明确展示并提交有边界授权')
check(floatingChat.includes('chatGenerationManager.start') && floatingChat.includes('createConversationAPI'), '浮动 AI 助手复用真实 Chat/LLM 会话与流式生成')
check(!floatingChat.includes('useAIAgent') && !fs.existsSync(path.join(root, 'frontend/src/services/aiAgent.ts')), '旧前端关键词助手执行路径已删除')
check(chatHub.includes('let targetId = currentConversationId') && chatHub.includes('chatGenerationManager.start(updatedMessages, targetId'), 'Chat Hub 首次发送会创建会话并在同一动作中启动生成')

console.log(`\nAgent teams frontend QA: ${passed}/${passed + failed} passed`)
process.exitCode = failed ? 1 : 0
