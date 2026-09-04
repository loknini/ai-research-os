import { useMemo } from 'react'
import { Background, Controls, MiniMap, ReactFlow, type Edge, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/utils'
import { DAG_NAME_MAP } from '@/utils/agentNodes'

interface SnapshotNode {
  id: string
  name?: string
  position?: { x: number; y: number }
}

interface Snapshot {
  nodes?: SnapshotNode[]
  edges?: Array<{ id?: string; source: string; target: string }>
  outputNodeId?: string
}

interface RunNodeState {
  nodeId: string
  name: string
  status: string
}

interface RunEventLike {
  type: string
  data?: Record<string, any>
}

const STATUS_STYLE: Record<string, string> = {
  pending: '1px solid hsl(var(--border))',
  ready: '1px solid #eab308',
  running: '2px solid #3b82f6',
  completed: '2px solid #22c55e',
  failed: '2px solid #ef4444',
  skipped: '1px dashed hsl(var(--border))',
  cancelled: '1px dashed hsl(var(--border))',
}

function statusDot(status: string): string {
  switch (status) {
    case 'completed': return 'bg-green-500'
    case 'running': return 'bg-blue-500 animate-pulse'
    case 'failed': return 'bg-red-500'
    case 'ready': return 'bg-yellow-500 animate-pulse'
    default: return 'bg-gray-400'
  }
}

export function RunGraph({
  teamSnapshot,
  nodes,
  events,
  selectedNodeId,
  onSelect,
}: {
  teamSnapshot?: Snapshot | null
  nodes: RunNodeState[]
  events: RunEventLike[]
  selectedNodeId?: string | null
  onSelect?: (nodeId: string) => void
}) {
  const statusMap = useMemo(() => {
    const m: Record<string, string> = {}
    for (const n of nodes) m[n.nodeId] = n.status
    return m
  }, [nodes])

  const nameMap = useMemo(() => {
    const m: Record<string, string> = {}
    for (const n of (teamSnapshot?.nodes || [])) {
      if (n.name && n.name !== '用户') m[n.id] = n.name
    }
    for (const n of nodes) {
      if (n.name && n.name !== '用户') m[n.nodeId] = n.name
    }
    return m
  }, [teamSnapshot, nodes])

  const iterationMap = useMemo(() => {
    const m: Record<string, number> = {}
    for (const ev of events) {
      const d = ev.data || {}
      const nid = (d.nodeId || d.node_id || '') as string
      const it = (d.iteration ?? d.iter ?? null) as number | null
      if (nid && typeof it === 'number') {
        m[nid] = Math.max(m[nid] ?? 0, it)
      }
    }
    return m
  }, [events])

  const completedSet = useMemo(() => {
    return new Set(nodes.filter((n) => n.status === 'completed').map((n) => n.nodeId))
  }, [nodes])

  const flowNodes: Node[] = useMemo(() => {
    const snapNodes = teamSnapshot?.nodes || []
    const base: SnapshotNode[] = snapNodes.length > 0
      ? snapNodes
      : nodes.map((n, i) => ({ id: n.nodeId, name: n.name, position: { x: (i % 4) * 220, y: Math.floor(i / 4) * 140 } }))
    const outputId = teamSnapshot?.outputNodeId
    return base.map((n, i) => {
      const status = statusMap[n.id] || 'pending'
      const name = (n.name && n.name !== '用户' ? n.name : null) || nameMap[n.id] || DAG_NAME_MAP[n.id] || n.id
      const pos = n.position || { x: (i % 4) * 220, y: Math.floor(i / 4) * 140 }
      const iter = iterationMap[n.id]
      return {
        id: n.id,
        position: pos,
        selected: selectedNodeId === n.id,
        data: {
          label: (
            <div className="min-w-[150px]">
              <div className="flex items-center gap-1.5">
                <span className={cn('h-2 w-2 rounded-full shrink-0', statusDot(status))} />
                <span className="text-sm font-medium truncate">{name}</span>
                {iter != null && iter > 0 && (
                  <Badge variant="secondary" className="text-[10px] px-1 py-0">第{iter}轮</Badge>
                )}
              </div>
              <div className="mt-1 flex items-center gap-1">
                <span className="text-[10px] text-muted-foreground">{status}</span>
                {outputId === n.id && <span className="text-[10px] text-primary">· 主输出</span>}
              </div>
            </div>
          ),
        },
        style: {
          border: STATUS_STYLE[status] || STATUS_STYLE.pending,
          borderRadius: 12,
          background: 'hsl(var(--card))',
          color: 'hsl(var(--card-foreground))',
          minWidth: 170,
          boxShadow: status === 'running' ? '0 0 0 3px rgba(59,130,246,.15)' : undefined,
        },
      }
    })
  }, [teamSnapshot, nodes, statusMap, nameMap, iterationMap, selectedNodeId])

  const flowEdges: Edge[] = useMemo(() => {
    const snapEdges = teamSnapshot?.edges || []
    if (snapEdges.length > 0) {
      return snapEdges.map((e, i) => {
        const animated = completedSet.has(e.source) && statusMap[e.target] === 'running'
        return {
          id: e.id || `${e.source}->${e.target}-${i}`,
          source: e.source,
          target: e.target,
          animated,
          style: { strokeWidth: animated ? 2.5 : 1.5 },
        }
      })
    }
    // fallback：按节点顺序链式
    const ids = flowNodes.map((n) => n.id)
    return ids.slice(1).map((id, i) => ({
      id: `${ids[i]}->${id}`,
      source: ids[i],
      target: id,
      animated: false,
    }))
  }, [teamSnapshot, flowNodes, completedSet, statusMap])

  if (flowNodes.length === 0) return null

  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      <div className="px-3 py-2 border-b text-xs text-muted-foreground">
        DAG 运行过程（左图右文双显，点击节点看分产物）
      </div>
      <div style={{ height: 440 }}>
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          onNodeClick={(_, node) => onSelect?.(node.id)}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <MiniMap pannable zoomable />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  )
}
