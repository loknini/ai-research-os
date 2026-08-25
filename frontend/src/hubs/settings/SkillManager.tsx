import { useState, useEffect, useCallback } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { toast } from '@/components/ui/toast'
import {
  Puzzle,
  RefreshCw,
  Play,
  Terminal,
  Loader2,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'

interface SkillInfo {
  name: string
  type: 'instruction' | 'tool'
  description: string
  enabled: boolean
  hasScript?: boolean
  path?: string
}

export default function SkillManager() {
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [toggling, setToggling] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [paramsDraft, setParamsDraft] = useState<Record<string, string>>({})
  const [running, setRunning] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, any>>({})

  const loadSkills = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await fetch('/api/skills')
      const data = await resp.json()
      if (data.success && Array.isArray(data.skills)) {
        setSkills(data.skills)
      } else {
        toast({ title: '加载技能列表失败', description: data.error || data.message, variant: 'error' })
      }
    } catch (e) {
      console.error('load skills error', e)
      toast({ title: '加载技能列表失败', description: '无法连接到后端服务器', variant: 'error' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadSkills()
  }, [loadSkills])

  const handleReload = async () => {
    try {
      const resp = await fetch('/api/skills/reload', { method: 'POST' })
      const data = await resp.json()
      if (data.success) {
        toast({ title: '已重新扫描技能目录', description: `生效技能 ${data.count} 个`, variant: 'success' })
      }
    } catch (e) {
      console.error('reload skills error', e)
    } finally {
      loadSkills()
    }
  }

  const handleToggle = async (name: string, enabled: boolean) => {
    setToggling(name)
    try {
      const resp = await fetch(`/api/skills/${encodeURIComponent(name)}/enabled`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      })
      const data = await resp.json()
      if (data.success) {
        setSkills((prev) => prev.map((s) => (s.name === name ? { ...s, enabled } : s)))
        toast({ title: enabled ? '已启用技能' : '已禁用技能', description: name, variant: 'success' })
      } else {
        toast({ title: '操作失败', description: data.error || data.message, variant: 'error' })
      }
    } catch (e) {
      console.error('toggle skill error', e)
      toast({ title: '操作失败', description: '无法连接到后端服务器', variant: 'error' })
    } finally {
      setToggling(null)
    }
  }

  const handleRun = async (name: string) => {
    const raw = (paramsDraft[name] || '{}').trim()
    let params: Record<string, any> = {}
    if (raw) {
      try {
        const parsed = JSON.parse(raw)
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          params = parsed
        } else {
          toast({ title: '参数必须是 JSON 对象', variant: 'error' })
          return
        }
      } catch (e) {
        toast({ title: '参数 JSON 解析失败', description: (e as Error).message, variant: 'error' })
        return
      }
    }
    setRunning(name)
    setResults((prev) => ({ ...prev, [name]: undefined }))
    try {
      const resp = await fetch(`/api/skills/${encodeURIComponent(name)}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ params }),
      })
      const data = await resp.json()
      if (data.success) {
        setResults((prev) => ({ ...prev, [name]: data.result }))
        toast({ title: '技能执行完成', description: name, variant: 'success' })
      } else {
        setResults((prev) => ({ ...prev, [name]: { error: data.error || data.message } }))
        toast({ title: '技能执行失败', description: data.error || data.message, variant: 'error' })
      }
    } catch (e) {
      console.error('run skill error', e)
      setResults((prev) => ({ ...prev, [name]: { error: '无法连接到后端服务器' } }))
      toast({ title: '技能执行失败', description: '无法连接到后端服务器', variant: 'error' })
    } finally {
      setRunning(null)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="p-2 bg-purple-500/10 rounded-lg">
            <Puzzle className="w-5 h-5 text-purple-500" />
          </div>
          <div className="flex-1">
            <CardTitle>技能管理 (Skills)</CardTitle>
            <CardDescription>
              后端 Agent 可调用的技能（目录式发现，对齐 Agent Skills 开放标准）。可在对话中让模型按描述自动调用，或用 <code>/skill &lt;名称&gt; {'{...}'}</code> 手动触发。
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={handleReload} disabled={loading}>
            {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
            重新扫描
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {skills.length === 0 && (
          <p className="text-sm text-muted-foreground">
            尚未发现任何技能。在 <code>backend/skills/&lt;name&gt;/SKILL.md</code> 放入技能目录即可被自动发现。
          </p>
        )}

        {skills.map((skill) => {
          const isOpen = expanded === skill.name
          const result = results[skill.name]
          return (
            <div
              key={skill.name}
              className="rounded-lg border border-border bg-muted/40 p-4 space-y-3"
            >
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-foreground">{skill.name}</span>
                    <Badge
                      className={
                        skill.type === 'tool'
                          ? 'bg-violet-500/10 text-violet-600'
                          : 'bg-emerald-500/10 text-emerald-600'
                      }
                    >
                      {skill.type === 'tool' ? '工具型' : '指令型'}
                    </Badge>
                    {!skill.enabled && (
                      <Badge variant="secondary" className="bg-gray-500/10 text-gray-500">
                        已禁用
                      </Badge>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground mt-1 break-words">
                    {skill.description || '（无描述）'}
                  </p>
                </div>

                {/* 启用开关 */}
                <label className="flex items-center gap-2 text-sm text-muted-foreground shrink-0">
                  <input
                    type="checkbox"
                    checked={skill.enabled}
                    disabled={toggling === skill.name}
                    onChange={(e) => handleToggle(skill.name, e.target.checked)}
                    className="rounded border-gray-300"
                  />
                  启用
                </label>
              </div>

              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setExpanded(isOpen ? null : skill.name)}
                >
                  {isOpen ? <ChevronUp className="w-4 h-4 mr-1" /> : <ChevronDown className="w-4 h-4 mr-1" />}
                  {isOpen ? '收起' : '运行'}
                </Button>
              </div>

              {isOpen && (
                <div className="space-y-2 pt-1">
                  <label className="text-xs font-medium text-muted-foreground">
                    参数 (JSON 对象，可留空传 {'{}'})
                  </label>
                  <Input
                    value={paramsDraft[skill.name] ?? '{}'}
                    onChange={(e) =>
                      setParamsDraft((prev) => ({ ...prev, [skill.name]: e.target.value }))
                    }
                    placeholder='{"arxiv_id":"1706.03762"}'
                    className="font-mono text-xs"
                  />
                  <Button size="sm" onClick={() => handleRun(skill.name)} disabled={running === skill.name}>
                    {running === skill.name ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <Play className="w-4 h-4 mr-2" />
                    )}
                    执行技能
                  </Button>

                  {result !== undefined && (
                    <div
                      className={`mt-2 rounded-md p-3 text-xs ${
                        result && result.success === false
                          ? 'bg-red-500/10 text-red-600'
                          : 'bg-emerald-500/10 text-emerald-700'
                      }`}
                    >
                      <div className="flex items-center gap-1.5 mb-1">
                        {result && result.success === false ? (
                          <XCircle className="w-3.5 h-3.5" />
                        ) : (
                          <CheckCircle2 className="w-3.5 h-3.5" />
                        )}
                        <span className="font-medium">执行结果</span>
                      </div>
                      <pre className="whitespace-pre-wrap break-words max-h-64 overflow-auto">
                        {JSON.stringify(result, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}

        <div className="flex items-start gap-2 pt-1 text-xs text-muted-foreground">
          <Terminal className="w-4 h-4 mt-0.5 shrink-0" />
          <p>
            提示：在任意对话中输入 <code>/skill arxiv_reader {'{"arxiv_id":"1706.03762"}'}</code> 即可手动调用技能；
            不带参数时模型会按各技能的 description 自动决定是否调用。
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
