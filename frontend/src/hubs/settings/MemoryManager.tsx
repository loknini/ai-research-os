import { useState, useEffect, useCallback } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/toast'

const textareaClass =
  'flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50'
import { Brain, Save, Plus, Sparkles, Loader2 } from 'lucide-react'

/**
 * 长期记忆管理面板（对应后端 /api/memory）。
 * 记忆按当前空间（X-Space-Key）隔离，每次聊天会被注入 system prompt，
 * 让 AI “越用越懂用户”。支持手动编辑、追加、以及从对话片段自动提炼。
 */
export default function MemoryManager() {
  const [content, setContent] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [observeDraft, setObserveDraft] = useState('')
  const [extractDraft, setExtractDraft] = useState('')
  const [extracting, setExtracting] = useState(false)

  const loadMemory = useCallback(async () => {
    try {
      const resp = await fetch('/api/memory')
      const data = await resp.json()
      if (data.success) {
        setContent(data.content || '')
        setLoaded(true)
      } else {
        toast({ title: '加载记忆失败', description: data.error || data.message, variant: 'error' })
      }
    } catch (e) {
      console.error('load memory error', e)
      toast({ title: '加载记忆失败', description: '无法连接到后端服务器', variant: 'error' })
    }
  }, [])

  useEffect(() => {
    loadMemory()
  }, [loadMemory])

  const handleSave = async () => {
    setSaving(true)
    try {
      const resp = await fetch('/api/memory', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })
      const data = await resp.json()
      if (data.success) {
        toast({ title: '记忆已保存', variant: 'success' })
      } else {
        toast({ title: '保存失败', description: data.error || data.message, variant: 'error' })
      }
    } catch (e) {
      console.error('save memory error', e)
      toast({ title: '保存失败', description: '无法连接到后端服务器', variant: 'error' })
    } finally {
      setSaving(false)
    }
  }

  const handleObserve = async () => {
    const entry = observeDraft.trim()
    if (!entry) {
      toast({ title: '请先填写要追加的内容', variant: 'error' })
      return
    }
    try {
      const resp = await fetch('/api/memory/observe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entry }),
      })
      const data = await resp.json()
      if (data.success) {
        setContent(data.content || '')
        setObserveDraft('')
        toast({ title: '已追加记忆', variant: 'success' })
      } else {
        toast({ title: '追加失败', description: data.error || data.message, variant: 'error' })
      }
    } catch (e) {
      console.error('observe memory error', e)
      toast({ title: '追加失败', description: '无法连接到后端服务器', variant: 'error' })
    }
  }

  // 把对话片段文本解析成 messages：每行 `角色: 内容`，未标注默认 user
  const parseDialogue = (text: string) => {
    const lines = text.split('\n').map((l) => l.trim()).filter(Boolean)
    return lines.map((line) => {
      const m = line.match(/^(用户|助手|user|assistant|system)\s*[:：]\s*(.*)$/i)
      if (m) {
        const roleMap: Record<string, string> = { 用户: 'user', user: 'user', 助手: 'assistant', assistant: 'assistant', system: 'system' }
        return { role: roleMap[m[1].toLowerCase()] || 'user', content: m[2] }
      }
      return { role: 'user', content: line }
    })
  }

  const handleExtract = async () => {
    const text = extractDraft.trim()
    if (!text) {
      toast({ title: '请先粘贴对话片段', variant: 'error' })
      return
    }
    const messages = parseDialogue(text)
    if (!messages.length) return
    setExtracting(true)
    try {
      const resp = await fetch('/api/memory/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages }),
      })
      const data = await resp.json()
      if (data.success) {
        setContent(data.content || '')
        setExtractDraft('')
        toast({ title: '已从对话提炼并写入记忆', variant: 'success' })
      } else {
        toast({ title: '提炼失败', description: data.error || data.message, variant: 'error' })
      }
    } catch (e) {
      console.error('extract memory error', e)
      toast({ title: '提炼失败', description: '无法连接到后端服务器', variant: 'error' })
    } finally {
      setExtracting(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="p-2 bg-amber-500/10 rounded-lg">
            <Brain className="w-5 h-5 text-amber-500" />
          </div>
          <div className="flex-1">
            <CardTitle>长期记忆 (Memory)</CardTitle>
            <CardDescription>
              按空间隔离的持久记忆（Markdown）。每次聊天会注入到对话的 system prompt，
              让 AI “越用越懂你”。可手动编辑，也可从对话片段自动提炼偏好与背景。
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">当前空间记忆内容</label>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="例如：&#10;- 用户是研究生，研究方向为多模态大模型&#10;- 偏好简洁的中文回答&#10;- 正在做 arXiv 论文综述，截止 8 月底"
            className={`min-h-[180px] font-mono text-xs ${textareaClass}`}
            disabled={!loaded}
          />
          <div className="flex gap-2">
            <Button size="sm" onClick={handleSave} disabled={saving || !loaded}>
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
              保存记忆
            </Button>
            <Button variant="outline" size="sm" onClick={loadMemory} disabled={!loaded}>
              重新加载
            </Button>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-muted/40 p-4 space-y-2">
          <label className="text-xs font-medium text-muted-foreground">追加一条记忆</label>
          <textarea
            value={observeDraft}
            onChange={(e) => setObserveDraft(e.target.value)}
            placeholder="直接写一条要记住的事实，如：用户喜欢用表格对比方案"
            className={`min-h-[72px] text-sm ${textareaClass}`}
          />
          <Button variant="outline" size="sm" onClick={handleObserve}>
            <Plus className="w-4 h-4 mr-2" />
            追加
          </Button>
        </div>

        <div className="rounded-lg border border-border bg-muted/40 p-4 space-y-2">
          <label className="text-xs font-medium text-muted-foreground">
            从对话片段自动提炼（每行一条，可用「用户: / 助手:」标注角色）
          </label>
          <textarea
            value={extractDraft}
            onChange={(e) => setExtractDraft(e.target.value)}
            placeholder={'用户: 我下周要交论文初稿\n助手: 好的，我帮你跟踪进度'}
            className={`min-h-[96px] text-sm ${textareaClass}`}
          />
          <Button variant="outline" size="sm" onClick={handleExtract} disabled={extracting}>
            {extracting ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Sparkles className="w-4 h-4 mr-2" />
            )}
            提炼并写入记忆
          </Button>
        </div>

        <p className="text-xs text-muted-foreground">
          提示：记忆仅在当前空间生效；切换到其它空间（或共享链接）会加载对应空间的记忆。
        </p>
      </CardContent>
    </Card>
  )
}
