import { useEffect, useState } from 'react'
import { Users } from 'lucide-react'
import { AgentWorkflow } from '@/components/agent/agent-workflow'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { SoftwareProject } from '@/types'

interface TeamOption {
  id: string
  name: string
  acceptedContexts: string[]
}

interface ProjectDraft {
  name?: string
  description?: string
  techStack?: string[]
  features?: string[]
  architecture?: string
  milestones?: Array<{ title?: string; name?: string; description?: string }>
}

interface IdeaFormDialogProps {
  ideaDescription: string
  onIdeaDescriptionChange: (value: string) => void
  onClose: () => void
  onFormDataChange: (data: Partial<SoftwareProject>) => void
  onShowCreateForm: (open: boolean) => void
}

export function IdeaFormDialog({
  ideaDescription,
  onIdeaDescriptionChange,
  onClose,
  onFormDataChange,
  onShowCreateForm
}: IdeaFormDialogProps) {
  const [teams, setTeams] = useState<TeamOption[]>([])
  const [teamId, setTeamId] = useState('builtin-software-planning')
  const [draft, setDraft] = useState<ProjectDraft | null>(null)

  useEffect(() => {
    fetch('/api/agent/teams')
      .then(response => response.json())
      .then(data => setTeams((data.teams || []).filter((team: TeamOption) =>
        team.acceptedContexts?.includes('software_idea'))))
      .catch(() => setTeams([]))
  }, [])

  const applyDraft = () => {
    if (!draft) return
    onFormDataChange({
      name: draft.name || ideaDescription.slice(0, 30),
      description: draft.description || ideaDescription,
      techStack: draft.techStack || [],
      status: 'design',
      features: (draft.features || []).map((feature, index) => ({
        id: String(index + 1), name: feature, description: feature,
        status: 'todo', priority: 'medium'
      })),
      architecture: { pattern: 'custom', components: [], diagram: draft.architecture || '' },
      milestones: (draft.milestones || []).map((milestone, index) => ({
        id: String(index + 1),
        name: milestone.title || milestone.name || `里程碑 ${index + 1}`,
        description: milestone.description || '',
        status: index === 0 ? 'in_progress' : 'pending'
      }))
    })
    onClose()
    onShowCreateForm(true)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <Card className="w-full max-w-5xl max-h-[92vh] overflow-y-auto">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="w-5 h-5 text-purple-500" />
            专家团队规划
          </CardTitle>
          <CardDescription>先生成并预览项目草案，确认后才应用到项目表单。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-[1fr_260px]">
            <textarea
              className="min-h-[110px] w-full resize-none rounded-md border border-input bg-background p-3"
              placeholder="描述你的软件想法、目标用户和关键约束……"
              value={ideaDescription}
              onChange={event => onIdeaDescriptionChange(event.target.value)}
            />
            <label className="text-sm font-medium">
              选择团队
              <select
                className="mt-2 h-10 w-full rounded-md border border-input bg-background px-3"
                value={teamId}
                onChange={event => setTeamId(event.target.value)}
              >
                {teams.map(team => <option key={team.id} value={team.id}>{team.name}</option>)}
              </select>
            </label>
          </div>

          <AgentWorkflow
            requirement={ideaDescription}
            teamId={teamId}
            context={{ kind: 'software_idea', variables: { idea: ideaDescription } }}
            onComplete={result => setDraft(result.primaryOutput as ProjectDraft)}
          />

          {draft && (
            <div className="rounded-lg border bg-muted/30 p-4">
              <div className="mb-2 font-medium">项目草案预览</div>
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap text-xs">
                {JSON.stringify(draft, null, 2)}
              </pre>
            </div>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>取消</Button>
            <Button disabled={!draft} onClick={applyDraft}>应用到项目</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
