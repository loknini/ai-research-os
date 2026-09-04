import { DragEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background, Controls, MiniMap, ReactFlow, ReactFlowProvider,
  addEdge, applyEdgeChanges, applyNodeChanges, useReactFlow,
  type Connection, type Edge, type EdgeChange, type Node, type NodeChange
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Bot, Copy, Download, Eye, Network, Pencil, Play, Plus, RefreshCw, Save, Trash2, Upload, Users } from 'lucide-react'
import { Header } from '@/components/layout/header'
import { AgentWorkflow } from '@/components/agent/agent-workflow'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useNavigate } from 'react-router-dom'

type ContextKind = 'generic' | 'software_idea' | 'software_project' | 'papers' | 'notes'

const CONTEXT_LABELS: Record<ContextKind, string> = {
  generic: '通用任务',
  software_idea: '软件想法',
  software_project: '软件研发',
  papers: '论文研读',
  notes: '知识综合'
}

interface TeamNodeSpec {
  id: string
  name: string
  description: string
  systemPrompt: string
  allowedTools: string[]
  model: string | null
  temperature: number | null
  maxTokens: number | null
  output: { type: 'text' | 'json_schema'; schema?: Record<string, unknown> }
  position: { x: number; y: number }
  stage?: 'analysis' | 'implementation' | 'testing' | 'review'
}

interface AgentTeam {
  schemaVersion: 1
  id?: string
  name: string
  description: string
  category: string
  workflowType?: 'dag' | 'development'
  acceptedContexts: ContextKind[]
  maxConcurrency: number
  approvalMode: 'auto' | 'manual' | 'strict'
  outputNodeId: string
  nodes: TeamNodeSpec[]
  edges: Array<{ id: string; source: string; target: string }>
  builtin?: boolean
  warnings?: string[]
}

interface RoleTemplate extends Omit<TeamNodeSpec, 'position'> {
  id: string
  builtin?: boolean
}

interface ToolCapability {
  name: string
  description: string
  source: string
  policy: 'safe' | 'sensitive' | 'dangerous'
}

const emptyTeam = (): AgentTeam => ({
  schemaVersion: 1,
  name: '未命名专家团队',
  description: '',
  category: 'custom',
  acceptedContexts: ['generic'],
  maxConcurrency: 2,
  approvalMode: 'manual',
  outputNodeId: '',
  nodes: [],
  edges: []
})

const emptyRole = (): RoleTemplate => ({
  id: '',
  name: '未命名角色',
  description: '',
  systemPrompt: '',
  allowedTools: [],
  model: null,
  temperature: 0.2,
  maxTokens: 2400,
  output: { type: 'text' }
})

async function requestJson(url: string, init?: RequestInit) {
  const response = await fetch(url, init)
  const data = await response.json()
  if (!response.ok || data.success === false) throw new Error(data.message || '请求失败')
  return data
}

function TeamEditor({
  initial, templates, tools, models, readOnly = false, onFetchModels, onSaved, onClose
}: {
  initial: AgentTeam
  templates: RoleTemplate[]
  tools: ToolCapability[]
  models: string[]
  readOnly?: boolean
  onFetchModels: () => Promise<void>
  onSaved: () => void
  onClose: () => void
}) {
  const [team, setTeam] = useState<AgentTeam>(() => structuredClone(initial))
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(team.nodes[0]?.id || null)
  const [message, setMessage] = useState('')
  const [schemaDrafts, setSchemaDrafts] = useState<Record<string, string>>({})
  const { screenToFlowPosition } = useReactFlow()

  const flowNodes = useMemo<Node[]>(() => team.nodes.map(node => ({
    id: node.id,
    position: node.position,
    data: { label: node.name },
    style: {
      border: node.id === team.outputNodeId ? '2px solid hsl(var(--primary))' : '1px solid hsl(var(--border))',
      borderRadius: 12,
      background: 'hsl(var(--card))',
      color: 'hsl(var(--card-foreground))',
      minWidth: 150
    }
  })), [team.nodes, team.outputNodeId])
  const flowEdges = useMemo<Edge[]>(() => team.edges, [team.edges])
  const selectedNode = team.nodes.find(node => node.id === selectedNodeId)

  const onNodesChange = (changes: NodeChange[]) => {
    const changed = applyNodeChanges(changes, flowNodes)
    setTeam(current => ({
      ...current,
      nodes: current.nodes.map(node => ({
        ...node,
        position: changed.find(value => value.id === node.id)?.position || node.position
      })).filter(node => changed.some(value => value.id === node.id))
    }))
  }
  const onEdgesChange = (changes: EdgeChange[]) => {
    const changed = applyEdgeChanges(changes, flowEdges)
    setTeam(current => ({ ...current, edges: changed.map(edge => ({
      id: edge.id, source: edge.source, target: edge.target
    })) }))
  }
  const onConnect = (connection: Connection) => {
    const id = `${connection.source}-${connection.target}-${crypto.randomUUID()}`
    const changed = addEdge({ ...connection, id }, flowEdges)
    setTeam(current => ({ ...current, edges: changed.map(edge => ({
      id: edge.id, source: edge.source, target: edge.target
    })) }))
  }
  const addTemplate = (template: RoleTemplate, position = { x: 120, y: 120 }) => {
    const id = `${template.id.replace(/^builtin-role-/, '')}-${crypto.randomUUID()}`
    const node: TeamNodeSpec = {
      ...structuredClone(template), id, position,
      allowedTools: [...(template.allowedTools || [])]
    }
    delete (node as TeamNodeSpec & { builtin?: boolean }).builtin
    setTeam(current => ({
      ...current, nodes: [...current.nodes, node],
      outputNodeId: current.outputNodeId || id
    }))
    setSelectedNodeId(id)
  }
  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    const template = templates.find(item => item.id === event.dataTransfer.getData('application/agent-role'))
    if (template) addTemplate(template, screenToFlowPosition({ x: event.clientX, y: event.clientY }))
  }
  const updateNode = (updates: Partial<TeamNodeSpec>) => {
    if (!selectedNodeId) return
    setTeam(current => ({
      ...current,
      nodes: current.nodes.map(node => node.id === selectedNodeId ? { ...node, ...updates } : node)
    }))
  }
  const save = async () => {
    setMessage('正在校验…')
    try {
      const method = team.id && !team.builtin ? 'PUT' : 'POST'
      const url = method === 'PUT' ? `/api/agent/teams/${team.id}` : '/api/agent/teams'
      const payload = structuredClone(team)
      for (const node of payload.nodes) {
        const draft = schemaDrafts[node.id]
        if (node.output.type === 'json_schema' && draft !== undefined) {
          try {
            node.output.schema = JSON.parse(draft)
          } catch {
            throw new Error(`节点“${node.name}”的 JSON Schema 不是合法 JSON`)
          }
        }
      }
      delete payload.builtin
      delete payload.warnings
      if (method === 'POST') delete payload.id
      const data = await requestJson(url, {
        method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      })
      setMessage(data.warnings?.length ? data.warnings.join('；') : '已保存')
      onSaved()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '保存失败')
    }
  }

  return (
    <div className={`grid h-[calc(100vh-8.5rem)] min-h-[650px] overflow-hidden rounded-xl border bg-card ${readOnly ? 'grid-cols-[1fr_340px]' : 'grid-cols-[230px_1fr_310px]'}`}>
      {!readOnly && <aside className="overflow-y-auto border-r p-3">
        <div className="mb-3 text-sm font-semibold">角色模板</div>
        <div className="space-y-2">
          {templates.map(template => (
            <button
              key={template.id}
              draggable
              onDragStart={event => event.dataTransfer.setData('application/agent-role', template.id)}
              onDoubleClick={() => addTemplate(template)}
              className="w-full rounded-lg border p-3 text-left hover:border-primary/60"
            >
              <div className="text-sm font-medium">{template.name}</div>
              <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">{template.description}</div>
            </button>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">拖入画布，或双击添加。模板会复制为节点快照。</p>
      </aside>}

      <section className="relative" onDrop={readOnly ? undefined : onDrop}
        onDragOver={readOnly ? undefined : event => event.preventDefault()}>
        <div className="absolute left-3 right-3 top-3 z-10 flex items-center gap-2 rounded-lg border bg-background/90 p-2 backdrop-blur">
          <Input value={team.name} disabled={readOnly} onChange={event => setTeam({ ...team, name: event.target.value })} />
          {readOnly && <Badge variant="secondary" className="shrink-0">内置团队 · 只读</Badge>}
          <Button size="sm" variant="outline" onClick={onClose}>{readOnly ? '关闭' : '退出'}</Button>
          {!readOnly && <Button size="sm" onClick={save}><Save className="mr-1 h-4 w-4" />校验并保存</Button>}
        </div>
        <ReactFlow
          nodes={flowNodes} edges={flowEdges}
          onNodesChange={readOnly ? undefined : onNodesChange}
          onEdgesChange={readOnly ? undefined : onEdgesChange}
          onConnect={readOnly ? undefined : onConnect}
          onNodeClick={(_, node) => setSelectedNodeId(node.id)} fitView
          nodesDraggable={!readOnly} nodesConnectable={!readOnly}
        >
          <Background /><MiniMap /><Controls />
        </ReactFlow>
        {message && <div className="absolute bottom-3 left-3 z-10 rounded bg-background px-3 py-2 text-xs shadow">{message}</div>}
      </section>

      <aside className="overflow-y-auto border-l p-4">
        <div className="mb-4 space-y-3">
          <label className="block text-xs font-medium">描述
            <textarea className="mt-1 min-h-20 w-full rounded border bg-background p-2 text-sm" value={team.description}
              readOnly={readOnly}
              onChange={event => setTeam({ ...team, description: event.target.value })} />
          </label>
          <label className="block text-xs font-medium">并发上限
            <Input type="number" min={1} max={4} value={team.maxConcurrency} disabled={readOnly}
              onChange={event => setTeam({ ...team, maxConcurrency: Number(event.target.value) })} />
          </label>
          <label className="block text-xs font-medium">审批模式
            <select className="mt-1 h-9 w-full rounded border bg-background px-2" value={team.approvalMode}
              disabled={readOnly}
              onChange={event => setTeam({ ...team, approvalMode: event.target.value as AgentTeam['approvalMode'] })}>
              <option value="manual">manual</option><option value="auto">auto</option><option value="strict">strict</option>
            </select>
          </label>
          {team.approvalMode === 'auto' && <p className="text-xs text-amber-600">auto 会自动执行 sensitive 工具；dangerous 工具仍会被拦截。</p>}
          <div className="text-xs font-medium">可用上下文</div>
          <div className="flex flex-wrap gap-1">
            {(['generic', 'software_idea', 'software_project', 'papers', 'notes'] as ContextKind[]).map(kind => (
              <button key={kind} disabled={readOnly} className={`rounded border px-2 py-1 text-xs ${team.acceptedContexts.includes(kind) ? 'bg-primary text-primary-foreground' : ''}`}
                onClick={() => setTeam({ ...team, acceptedContexts: team.acceptedContexts.includes(kind)
                  ? team.acceptedContexts.filter(value => value !== kind) : [...team.acceptedContexts, kind] })}>{CONTEXT_LABELS[kind]}</button>
            ))}
          </div>
        </div>

        {selectedNode ? (
          <div className="space-y-3 border-t pt-4">
            <div className="font-semibold">节点配置</div>
            <Input value={selectedNode.name} disabled={readOnly} onChange={event => updateNode({ name: event.target.value })} />
            <textarea className="min-h-20 w-full rounded border bg-background p-2 text-sm" value={selectedNode.description}
              readOnly={readOnly}
              onChange={event => updateNode({ description: event.target.value })} placeholder="任务说明" />
            <textarea className="min-h-32 w-full rounded border bg-background p-2 text-sm" value={selectedNode.systemPrompt}
              readOnly={readOnly}
              onChange={event => updateNode({ systemPrompt: event.target.value })} placeholder="System prompt" />
            <div className="flex gap-2">
              <Input list="team-node-models" value={selectedNode.model || ''} disabled={readOnly}
                onChange={event => updateNode({ model: event.target.value || null })} placeholder="模型 ID（空值继承全局）" />
              {!readOnly && <Button size="icon" variant="outline" title="读取模型列表" onClick={() => void onFetchModels()}><RefreshCw className="h-4 w-4" /></Button>}
              <datalist id="team-node-models">{models.map(model => <option key={model} value={model} />)}</datalist>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Input type="number" step="0.1" min="0" max="2" value={selectedNode.temperature ?? ''} disabled={readOnly}
                onChange={event => updateNode({ temperature: event.target.value ? Number(event.target.value) : null })} placeholder="temperature" />
              <Input type="number" min="1" max="32768" value={selectedNode.maxTokens ?? ''} disabled={readOnly}
                onChange={event => updateNode({ maxTokens: event.target.value ? Number(event.target.value) : null })} placeholder="maxTokens" />
            </div>
            <label className="block text-xs font-medium">输出契约
              <select className="mt-1 h-9 w-full rounded border bg-background px-2" value={selectedNode.output.type}
                disabled={readOnly}
                onChange={event => updateNode({ output: event.target.value === 'text' ? { type: 'text' } : {
                  type: 'json_schema', schema: { type: 'object' }
                } })}>
                <option value="text">Text</option><option value="json_schema">JSON Schema</option>
              </select>
            </label>
            {selectedNode.output.type === 'json_schema' && (
              <textarea className="min-h-32 w-full rounded border bg-background p-2 font-mono text-xs"
                value={schemaDrafts[selectedNode.id] ?? JSON.stringify(selectedNode.output.schema || {}, null, 2)}
                readOnly={readOnly}
                onChange={event => {
                  const value = event.target.value
                  setSchemaDrafts(current => ({ ...current, [selectedNode.id]: value }))
                  try { updateNode({ output: { type: 'json_schema', schema: JSON.parse(value) } }) } catch { /* keep draft until valid */ }
                }} />
            )}
            <div className="text-xs font-medium">允许工具</div>
            <div className="max-h-44 space-y-1 overflow-y-auto">
              {tools.map(tool => (
                <label key={tool.name} className="flex items-start gap-2 rounded p-1 text-xs hover:bg-muted">
                  <input type="checkbox" checked={selectedNode.allowedTools.includes(tool.name)}
                    disabled={readOnly}
                    onChange={() => updateNode({ allowedTools: selectedNode.allowedTools.includes(tool.name)
                      ? selectedNode.allowedTools.filter(name => name !== tool.name)
                      : [...selectedNode.allowedTools, tool.name] })} />
                  <span>{tool.name} <Badge variant="outline" className="ml-1 text-[10px]">{tool.policy}</Badge></span>
                </label>
              ))}
            </div>
            {selectedNode.allowedTools.some(name => tools.find(tool => tool.name === name)?.policy !== 'safe') &&
              <p className="text-xs text-amber-600">该节点包含 sensitive 或 dangerous 工具；系统安全策略始终生效，团队配置不能降低其等级。</p>}
            {!readOnly && <Button size="sm" variant="outline" className="w-full" onClick={() => setTeam({ ...team, outputNodeId: selectedNode.id })}>设为主要输出</Button>}
            {!readOnly && <Button size="sm" variant="destructive" className="w-full" onClick={() => {
              setTeam({ ...team, nodes: team.nodes.filter(node => node.id !== selectedNode.id),
                edges: team.edges.filter(edge => edge.source !== selectedNode.id && edge.target !== selectedNode.id),
                outputNodeId: team.outputNodeId === selectedNode.id ? '' : team.outputNodeId })
              setSelectedNodeId(null)
            }}>删除节点</Button>}
          </div>
        ) : <p className="text-sm text-muted-foreground">选择一个节点进行配置。</p>}
      </aside>
    </div>
  )
}

function RoleTemplateEditor({
  initial, tools, models, readOnly = false, onFetchModels, onSaved, onClose
}: {
  initial: RoleTemplate
  tools: ToolCapability[]
  models: string[]
  readOnly?: boolean
  onFetchModels: () => Promise<void>
  onSaved: () => void
  onClose: () => void
}) {
  const [role, setRole] = useState<RoleTemplate>(() => structuredClone(initial))
  const [schemaDraft, setSchemaDraft] = useState(() => JSON.stringify(initial.output.schema || {}, null, 2))
  const [message, setMessage] = useState('')

  const save = async () => {
    try {
      const payload = structuredClone(role)
      delete (payload as Partial<RoleTemplate>).id
      delete payload.builtin
      if (payload.output.type === 'json_schema') {
        try {
          payload.output.schema = JSON.parse(schemaDraft)
        } catch {
          throw new Error('JSON Schema 不是合法 JSON')
        }
      }
      const method = role.id ? 'PUT' : 'POST'
      await requestJson(method === 'PUT' ? `/api/agent/role-templates/${role.id}` : '/api/agent/role-templates', {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      onSaved()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '保存失败')
    }
  }

  return (
    <Card className="max-w-4xl">
      <CardHeader><CardTitle>{readOnly ? '查看角色模板' : role.id ? '编辑角色模板' : '新建角色模板'}</CardTitle>
        <CardDescription>{readOnly ? '这是内置只读模板；你可以查看完整配置，克隆后再修改。' : '模板拖入团队时会复制为独立节点快照，之后修改模板不会影响已有团队。'}</CardDescription></CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2">
        <div className="space-y-3">
          <Input value={role.name} disabled={readOnly} onChange={event => setRole({ ...role, name: event.target.value })} placeholder="角色名称" />
          <textarea className="min-h-20 w-full rounded border bg-background p-2 text-sm" value={role.description}
            readOnly={readOnly}
            onChange={event => setRole({ ...role, description: event.target.value })} placeholder="角色说明" />
          <textarea className="min-h-40 w-full rounded border bg-background p-2 text-sm" value={role.systemPrompt}
            readOnly={readOnly}
            onChange={event => setRole({ ...role, systemPrompt: event.target.value })} placeholder="System prompt" />
          <div className="flex gap-2">
            <Input list="role-template-models" value={role.model || ''} disabled={readOnly}
              onChange={event => setRole({ ...role, model: event.target.value || null })} placeholder="模型 ID（空值继承全局）" />
            {!readOnly && <Button size="icon" variant="outline" title="读取模型列表" onClick={() => void onFetchModels()}><RefreshCw className="h-4 w-4" /></Button>}
            <datalist id="role-template-models">{models.map(model => <option key={model} value={model} />)}</datalist>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Input type="number" step="0.1" min="0" max="2" value={role.temperature ?? ''} disabled={readOnly}
              onChange={event => setRole({ ...role, temperature: event.target.value ? Number(event.target.value) : null })} placeholder="temperature" />
            <Input type="number" min="1" max="32768" value={role.maxTokens ?? ''} disabled={readOnly}
              onChange={event => setRole({ ...role, maxTokens: event.target.value ? Number(event.target.value) : null })} placeholder="maxTokens" />
          </div>
        </div>
        <div className="space-y-3">
          <label className="block text-xs font-medium">输出契约
            <select className="mt-1 h-9 w-full rounded border bg-background px-2" value={role.output.type}
              disabled={readOnly}
              onChange={event => {
                const output = event.target.value === 'text' ? { type: 'text' as const }
                  : { type: 'json_schema' as const, schema: { type: 'object' } }
                setRole({ ...role, output })
                setSchemaDraft(JSON.stringify(output.type === 'json_schema' ? output.schema : {}, null, 2))
              }}>
              <option value="text">Text</option><option value="json_schema">JSON Schema</option>
            </select>
          </label>
          {role.output.type === 'json_schema' && <textarea className="min-h-40 w-full rounded border bg-background p-2 font-mono text-xs"
            value={schemaDraft} readOnly={readOnly} onChange={event => setSchemaDraft(event.target.value)} />}
          <div className="text-xs font-medium">允许工具</div>
          <div className="max-h-52 space-y-1 overflow-y-auto rounded border p-2">
            {tools.map(tool => (
              <label key={tool.name} className="flex items-start gap-2 rounded p-1 text-xs hover:bg-muted">
                <input type="checkbox" checked={role.allowedTools.includes(tool.name)}
                  disabled={readOnly}
                  onChange={() => setRole({ ...role, allowedTools: role.allowedTools.includes(tool.name)
                    ? role.allowedTools.filter(name => name !== tool.name)
                    : [...role.allowedTools, tool.name] })} />
                <span>{tool.name} <Badge variant="outline" className="ml-1 text-[10px]">{tool.policy}</Badge>
                  <span className="ml-1 text-muted-foreground">{tool.description}</span></span>
              </label>
            ))}
          </div>
          {role.allowedTools.some(name => tools.find(tool => tool.name === name)?.policy !== 'safe') &&
            <p className="text-xs text-amber-600">该模板包含有副作用的工具；实际运行仍受团队审批模式和系统安全策略约束。</p>}
        </div>
        <div className="flex items-center gap-2 md:col-span-2">
          {!readOnly && <Button onClick={() => void save()}><Save className="mr-2 h-4 w-4" />保存模板</Button>}
          <Button variant="outline" onClick={onClose}>{readOnly ? '关闭' : '取消'}</Button>
          {message && <span className="text-sm text-destructive">{message}</span>}
        </div>
      </CardContent>
    </Card>
  )
}

export default function TeamsHub() {
  const navigate = useNavigate()
  const [teams, setTeams] = useState<AgentTeam[]>([])
  const [templates, setTemplates] = useState<RoleTemplate[]>([])
  const [tools, setTools] = useState<ToolCapability[]>([])
  const [models, setModels] = useState<string[]>([])
  const [view, setView] = useState<'teams' | 'editor' | 'roles'>('teams')
  const [editing, setEditing] = useState<AgentTeam>(emptyTeam())
  const [editorReadOnly, setEditorReadOnly] = useState(false)
  const [editingRole, setEditingRole] = useState<RoleTemplate | null>(null)
  const [roleReadOnly, setRoleReadOnly] = useState(false)
  const [runTeam, setRunTeam] = useState<AgentTeam | null>(null)
  const [requirement, setRequirement] = useState('')
  const [runOutput, setRunOutput] = useState<unknown>(null)
  const [runNodeStatuses, setRunNodeStatuses] = useState<Record<string, string>>({})
  const [useContexts, setUseContexts] = useState<Record<string, ContextKind>>({})
  const importRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    const [teamData, roleData, toolData] = await Promise.all([
      requestJson('/api/agent/teams'), requestJson('/api/agent/role-templates'), requestJson('/api/agent/tools')
    ])
    setTeams(teamData.teams || [])
    setTemplates(roleData.roleTemplates || [])
    setTools(toolData.tools || [])
  }, [])
  useEffect(() => { void load() }, [load])

  const runFlowNodes = useMemo<Node[]>(() => (runTeam?.nodes || []).map(node => {
    const status = runNodeStatuses[node.id] || 'pending'
    const border = status === 'completed' ? '#22c55e' : status === 'failed' ? '#ef4444'
      : status === 'running' ? '#3b82f6' : status === 'skipped' || status === 'cancelled' ? '#94a3b8'
        : 'hsl(var(--border))'
    return {
      id: node.id, position: node.position, data: { label: `${node.name} · ${status}` },
      style: { border: `2px solid ${border}`, borderRadius: 12, background: 'hsl(var(--card))',
        color: 'hsl(var(--card-foreground))', minWidth: 160, opacity: status === 'skipped' ? 0.55 : 1 }
    }
  }), [runTeam, runNodeStatuses])
  const runFlowEdges = useMemo<Edge[]>(() => runTeam?.edges || [], [runTeam])

  const handleRunEvent = useCallback((event: Record<string, any>) => {
    const statusByType: Record<string, string> = {
      node_queued: 'queued', node_start: 'running', node_complete: 'completed',
      node_failed: 'failed', node_skipped: 'skipped'
    }
    if (event.nodeId && statusByType[event.type]) {
      setRunNodeStatuses(previous => ({ ...previous, [event.nodeId]: statusByType[event.type] }))
    } else if (event.type === 'run_cancelled') {
      setRunNodeStatuses(previous => Object.fromEntries(Object.entries(previous).map(([id, status]) => [
        id, status === 'completed' || status === 'failed' ? status : 'cancelled'
      ])))
    }
  }, [])

  const fetchModels = async () => {
    try {
      const data = await requestJson('/api/settings/llm/models')
      setModels(data.models || [])
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '读取模型列表失败')
    }
  }

  const clone = async (id: string) => { await requestJson(`/api/agent/teams/${id}/clone`, { method: 'POST' }); await load() }
  const remove = async (id: string) => { if (window.confirm('确定删除这个团队？')) { await requestJson(`/api/agent/teams/${id}`, { method: 'DELETE' }); await load() } }
  const exportTeam = async (team: AgentTeam) => {
    const response = await fetch(`/api/agent/teams/${team.id}/export`)
    if (!response.ok) {
      window.alert('导出团队失败')
      return
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${team.name}.json`; anchor.click()
    URL.revokeObjectURL(url)
  }
  const importTeam = async (file?: File) => {
    if (!file) return
    await requestJson('/api/agent/teams/import', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: await file.text()
    })
    await load()
  }

  const goUseTeam = (team: AgentTeam, kind: ContextKind) => {
    if (kind === 'generic') {
      setRunOutput(null); setRunNodeStatuses({}); setRunTeam(team)
      return
    }
    const teamId = encodeURIComponent(team.id || '')
    const destinations: Record<Exclude<ContextKind, 'generic'>, string> = {
      software_idea: `/lab?tab=software&action=idea&teamId=${teamId}`,
      software_project: `/lab?tab=software&action=develop&teamId=${teamId}`,
      papers: `/paper?action=expert-review&teamId=${teamId}`,
      notes: `/knowledge?action=knowledge-synthesis&teamId=${teamId}`
    }
    navigate(destinations[kind])
  }

  if (view === 'editor') return (
    <div className="h-full overflow-auto p-6">
      <ReactFlowProvider>
        <TeamEditor initial={editing} templates={templates} tools={tools} models={models} readOnly={editorReadOnly} onFetchModels={fetchModels}
          onClose={() => setView('teams')} onSaved={async () => { await load(); setView('teams') }} />
      </ReactFlowProvider>
    </div>
  )

  return (
    <div className="h-full overflow-y-auto">
      <Header title="专家团队" />
      <div className="space-y-6 p-6">
        <div className="flex flex-wrap gap-2">
          <Button variant={view === 'teams' ? 'default' : 'outline'} onClick={() => setView('teams')}><Users className="mr-2 h-4 w-4" />团队</Button>
          <Button variant={view === 'roles' ? 'default' : 'outline'} onClick={() => setView('roles')}><Bot className="mr-2 h-4 w-4" />角色模板</Button>
          <Button variant="outline" onClick={() => { setEditing(emptyTeam()); setEditorReadOnly(false); setView('editor') }}><Plus className="mr-2 h-4 w-4" />新建团队</Button>
          {view === 'roles' && <Button variant="outline" onClick={() => { setEditingRole(emptyRole()); setRoleReadOnly(false) }}><Plus className="mr-2 h-4 w-4" />新建角色</Button>}
          <Button variant="outline" onClick={() => importRef.current?.click()}><Upload className="mr-2 h-4 w-4" />导入</Button>
          <input ref={importRef} type="file" accept="application/json" className="hidden" onChange={event => void importTeam(event.target.files?.[0])} />
        </div>

        {view === 'roles' ? (
          <div className="space-y-4">
            {editingRole && <RoleTemplateEditor initial={editingRole} tools={tools} models={models} readOnly={roleReadOnly} onFetchModels={fetchModels}
              onClose={() => setEditingRole(null)} onSaved={async () => { setEditingRole(null); await load() }} />}
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {templates.map(template => (
                <Card key={template.id}><CardHeader><CardTitle className="text-base">{template.name}</CardTitle><CardDescription>{template.description}</CardDescription></CardHeader>
                  <CardContent className="flex justify-between"><Badge>{template.builtin ? '内置' : '我的'}</Badge>
                    <div className="flex gap-2">
                      {template.builtin
                        ? <Button size="sm" variant="outline" onClick={() => { setEditingRole(template); setRoleReadOnly(true) }}><Eye className="mr-1 h-4 w-4" />查看</Button>
                        : <Button size="sm" variant="outline" title="编辑" onClick={() => { setEditingRole(template); setRoleReadOnly(false) }}><Pencil className="h-4 w-4" /></Button>}
                      <Button size="sm" variant="outline" title="克隆" onClick={async () => { await requestJson(`/api/agent/role-templates/${template.id}/clone`, { method: 'POST' }); await load() }}><Copy className="h-4 w-4" /></Button>
                      {!template.builtin && <Button size="sm" variant="destructive" title="删除" onClick={async () => {
                        if (window.confirm('确定删除这个角色模板？')) {
                          await requestJson(`/api/agent/role-templates/${template.id}`, { method: 'DELETE' }); await load()
                        }
                      }}><Trash2 className="h-4 w-4" /></Button>}
                    </div>
                  </CardContent></Card>
              ))}
            </div>
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {teams.map(team => (
              <Card key={team.id} className="flex flex-col"><CardHeader>
                <div className="flex items-center justify-between"><Badge variant={team.builtin ? 'secondary' : 'default'}>{team.builtin ? '内置' : '我的团队'}</Badge><Network className="h-5 w-5 text-muted-foreground" /></div>
                <CardTitle className="text-lg">{team.name}</CardTitle><CardDescription>{team.description}</CardDescription>
              </CardHeader><CardContent className="mt-auto space-y-3">
                <div className="flex flex-wrap gap-1">{team.acceptedContexts.map(kind => <Badge key={kind} variant="outline">{CONTEXT_LABELS[kind]}</Badge>)}</div>
                <div className="text-xs text-muted-foreground">{team.nodes.length} 个节点 · {team.workflowType === 'development' ? '固定研发流程' : `并发 ${team.maxConcurrency}`} · {team.approvalMode}</div>
                <div className="flex flex-wrap gap-2">
                  {team.acceptedContexts.length > 1 && <select
                    aria-label={`${team.name} 使用场景`}
                    className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                    value={useContexts[team.id || team.name] || team.acceptedContexts[0]}
                    onChange={event => setUseContexts(current => ({ ...current, [team.id || team.name]: event.target.value as ContextKind }))}
                  >{team.acceptedContexts.map(kind => <option key={kind} value={kind}>{CONTEXT_LABELS[kind]}</option>)}</select>}
                  <Button size="sm" onClick={() => goUseTeam(team,
                    useContexts[team.id || team.name] || team.acceptedContexts[0])}>去使用</Button>
                  {team.builtin ? <>
                    <Button size="sm" variant="outline" onClick={() => { setEditing(team); setEditorReadOnly(true); setView('editor') }}><Eye className="mr-1 h-4 w-4" />查看</Button>
                    <Button size="sm" variant="outline" onClick={() => void clone(team.id!)}><Copy className="mr-1 h-4 w-4" />克隆</Button>
                  </> : <Button size="sm" onClick={() => { setEditing(team); setEditorReadOnly(false); setView('editor') }}>编排</Button>}
                  <Button size="sm" variant="outline" onClick={() => void exportTeam(team)}><Download className="h-4 w-4" /></Button>
                  {team.acceptedContexts.includes('generic') && <Button size="sm" variant="outline" onClick={() => goUseTeam(team, 'generic')}><Play className="mr-1 h-4 w-4" />试运行</Button>}
                  {!team.builtin && <Button size="sm" variant="destructive" onClick={() => void remove(team.id!)}><Trash2 className="h-4 w-4" /></Button>}
                </div>
              </CardContent></Card>
            ))}
          </div>
        )}

        {runTeam && (
          <Card><CardHeader><CardTitle>试运行：{runTeam.name}</CardTitle><CardDescription>无 Hub 实体上下文，结果不会自动写入任何业务数据。</CardDescription></CardHeader>
            <CardContent className="space-y-4"><textarea className="min-h-24 w-full rounded border bg-background p-3" value={requirement} onChange={event => setRequirement(event.target.value)} placeholder="输入目标……" />
              <div className="grid gap-4 xl:grid-cols-2">
                <div className="h-[520px] overflow-hidden rounded-lg border">
                  <ReactFlow nodes={runFlowNodes} edges={runFlowEdges} nodesDraggable={false}
                    nodesConnectable={false} elementsSelectable={false} fitView>
                    <Background /><MiniMap /><Controls showInteractive={false} />
                  </ReactFlow>
                </div>
                <AgentWorkflow requirement={requirement} teamId={runTeam.id} context={{ kind: 'generic', variables: {} }}
                  onEvent={handleRunEvent} onComplete={result => setRunOutput(result.primaryOutput)} />
              </div>
              {runOutput !== null && <div className="rounded border bg-muted/30 p-3"><pre className="max-h-64 overflow-auto whitespace-pre-wrap text-sm">{typeof runOutput === 'string' ? runOutput : JSON.stringify(runOutput, null, 2)}</pre>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => navigator.clipboard?.writeText(typeof runOutput === 'string' ? runOutput : JSON.stringify(runOutput, null, 2))}>复制</Button>
                  <Button size="sm" variant="outline" onClick={() => {
                    const content = typeof runOutput === 'string' ? runOutput : JSON.stringify(runOutput, null, 2)
                    const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }))
                    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'team-result.md'; anchor.click(); URL.revokeObjectURL(url)
                  }}>下载 Markdown</Button>
                  <Button size="sm" onClick={async () => {
                    const value = runOutput as { title?: string; markdown?: string; tags?: string[] }
                    await requestJson('/api/notes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
                      title: value?.title || `${runTeam.name} 结果`, content: value?.markdown || (typeof runOutput === 'string' ? runOutput : JSON.stringify(runOutput, null, 2)),
                      type: 'note', tags: value?.tags || ['专家团队'], aiGenerated: true
                    }) })
                  }}>保存为笔记</Button>
                </div></div>}
              <Button variant="outline" onClick={() => setRunTeam(null)}>关闭</Button>
            </CardContent></Card>
        )}
      </div>
    </div>
  )
}
