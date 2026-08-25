import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Users } from 'lucide-react'
import { AgentWorkflow } from '@/components/agent/agent-workflow'
import type { SoftwareProject } from '@/types'

interface IdeaFormDialogProps {
  ideaDescription: string
  onIdeaDescriptionChange: (value: string) => void
  onClose: () => void
  onFormDataChange: (data: Partial<SoftwareProject>) => void
  onShowCreateForm: (open: boolean) => void
}

/** 「从想法开始」多 Agent 协作对话框（对应原容器内 532–593 行） */
export function IdeaFormDialog({
  ideaDescription,
  onIdeaDescriptionChange,
  onClose,
  onFormDataChange,
  onShowCreateForm
}: IdeaFormDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <Card className="w-full max-w-4xl max-h-[90vh] overflow-y-auto">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="w-5 h-5 text-purple-500" />
            多 Agent 协作规划
          </CardTitle>
          <CardDescription>
            描述你的软件想法，Architect + Planner Agent 将协作完成技术方案和任务规划
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <textarea
            className="w-full min-h-[100px] p-3 rounded-md border border-input bg-background resize-none"
            placeholder="例如：我想开发一个个人知识管理工具，可以收集网页、做笔记，并支持全文搜索..."
            value={ideaDescription}
            onChange={(e) => onIdeaDescriptionChange(e.target.value)}
          />

          {/* 多 Agent 协作组件 */}
          <AgentWorkflow
            requirement={ideaDescription}
            onComplete={(result) => {
              if (result.architectOutput?.structured) {
                const structured = result.architectOutput.structured
                onFormDataChange({
                  name: structured.overview?.slice(0, 30) || ideaDescription.slice(0, 20),
                  description: structured.overview || ideaDescription,
                  techStack: structured.tech_stack || [],
                  status: 'design',
                  features:
                    structured.modules?.map((m: any) => ({
                      name: m.name,
                      description: m.description,
                      status: 'pending'
                    })) || [],
                  architecture: {
                    pattern: structured.modules?.length > 0 ? '模块化架构' : '单体架构',
                    components: structured.modules?.map((m: any) => m.name) || []
                  },
                  milestones:
                    result.plannerOutput?.structured?.phases?.map(
                      (p: any, idx: number) => ({
                        id: String(idx + 1),
                        name: p.name,
                        description: `${p.tasks?.length || 0} 个任务`,
                        status: idx === 0 ? 'in_progress' : 'pending'
                      })
                    ) || []
                })
                onClose()
                onShowCreateForm(true)
              }
            }}
          />

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>
              取消
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
