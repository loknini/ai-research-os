import { useEffect, useMemo, useState } from 'react'
import { AgentWorkflow } from './agent-workflow'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

type ContextKind = 'papers' | 'notes'

interface EntityOption { id: string; title: string }
interface TeamOption { id: string; name: string; acceptedContexts: string[] }

export function TeamContextRunDialog({
  kind, entities, initialIds, defaultTeamId, onClose, onApply, applyLabel
}: {
  kind: ContextKind
  entities: EntityOption[]
  initialIds: string[]
  defaultTeamId: string
  onClose: () => void
  onApply: (output: unknown, entityIds: string[]) => Promise<void> | void
  applyLabel: string
}) {
  const [teams, setTeams] = useState<TeamOption[]>([])
  const [teamId, setTeamId] = useState(defaultTeamId)
  const [selected, setSelected] = useState<Set<string>>(new Set(initialIds))
  const [requirement, setRequirement] = useState(kind === 'papers'
    ? '比较这些论文的方法、证据、创新性与局限，生成一份可复用的研读报告。'
    : '综合这些笔记，识别关联、矛盾和证据空缺，生成一篇新的知识笔记。')
  const [output, setOutput] = useState<unknown>(null)
  const ids = useMemo(() => Array.from(selected).slice(0, 20), [selected])

  useEffect(() => {
    fetch('/api/agent/teams').then(response => response.json()).then(data => {
      setTeams((data.teams || []).filter((team: TeamOption) => team.acceptedContexts?.includes(kind)))
    }).catch(() => setTeams([]))
  }, [kind])

  const copy = () => navigator.clipboard?.writeText(
    typeof output === 'string' ? output : JSON.stringify(output, null, 2))
  const download = () => {
    const content = typeof output === 'object' && output && 'markdown' in output
      ? String((output as { markdown: string }).markdown)
      : (typeof output === 'string' ? output : JSON.stringify(output, null, 2))
    const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'expert-team-result.md'; anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4">
      <Card className="max-h-[94vh] w-full max-w-6xl overflow-y-auto">
        <CardHeader><CardTitle>{kind === 'papers' ? '论文研读团队' : '知识综合团队'}</CardTitle>
          <CardDescription>团队只能读取当前空间中选中的实体；完成后由你决定是否保存。</CardDescription></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
            <div className="space-y-3">
              <label className="block text-sm font-medium">团队
                <select className="mt-1 h-10 w-full rounded border bg-background px-3" value={teamId} onChange={event => setTeamId(event.target.value)}>
                  {teams.map(team => <option key={team.id} value={team.id}>{team.name}</option>)}
                </select>
              </label>
              <label className="block text-sm font-medium">运行目标
                <textarea className="mt-1 min-h-28 w-full rounded border bg-background p-2" value={requirement} onChange={event => setRequirement(event.target.value)} />
              </label>
              <div className="text-sm font-medium">选择实体（{ids.length}/20）</div>
              <div className="max-h-64 space-y-1 overflow-y-auto rounded border p-2">
                {entities.map(entity => <label key={entity.id} className="flex gap-2 rounded p-1 text-sm hover:bg-muted">
                  <input type="checkbox" checked={selected.has(entity.id)} onChange={() => setSelected(current => {
                    const next = new Set(current)
                    if (next.has(entity.id)) next.delete(entity.id)
                    else if (next.size < 20) next.add(entity.id)
                    return next
                  })} /> <span className="line-clamp-2">{entity.title}</span>
                </label>)}
              </div>
            </div>
            <AgentWorkflow requirement={requirement} teamId={teamId}
              context={{ kind, entityIds: ids, variables: {} }}
              onComplete={result => setOutput(result.primaryOutput)} />
          </div>
          {output !== null && <div className="rounded-lg border bg-muted/30 p-4"><div className="mb-2 font-medium">结果预览</div>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-sm">{typeof output === 'string' ? output : JSON.stringify(output, null, 2)}</pre></div>}
          <div className="flex justify-end gap-2"><Button variant="outline" onClick={onClose}>关闭</Button>
            <Button variant="outline" disabled={output === null} onClick={copy}>复制</Button>
            <Button variant="outline" disabled={output === null} onClick={download}>下载 Markdown</Button>
            <Button disabled={output === null || ids.length === 0} onClick={() => void onApply(output, ids)}>{applyLabel}</Button></div>
        </CardContent>
      </Card>
    </div>
  )
}
