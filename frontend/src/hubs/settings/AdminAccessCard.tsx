import { apiRequest } from '@/services/api'
import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, Eye, EyeOff, KeyRound, Loader2, ShieldAlert, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import { getAdminSessionToken, setAdminSessionToken } from '@/services/adminAccess'

type AccessState = { ok: boolean; message: string } | null

export default function AdminAccessCard({ onVerified }: { onVerified?: () => void }) {
  const [token, setToken] = useState(() => getAdminSessionToken())
  const [showToken, setShowToken] = useState(false)
  const [checking, setChecking] = useState(false)
  const [state, setState] = useState<AccessState>(null)

  const verify = useCallback(async (candidate: string, quiet = false) => {
    setChecking(true)
    setAdminSessionToken(candidate)
    try {
      const response = await apiRequest('/api/settings/llm', { cache: 'no-store' })
      if (!response.ok) {
        let message = `管理访问验证失败（HTTP ${response.status}）`
        try {
          const body = await response.json()
          message = body.message || body.detail || message
        } catch {
          // Keep the HTTP status fallback.
        }
        setAdminSessionToken('')
        setState({ ok: false, message })
        if (!quiet) toast({ title: '管理访问未授权', description: message, variant: 'error' })
        return
      }
      const message = candidate.trim()
        ? '管理令牌有效；本标签页已解锁系统级操作。'
        : '当前请求来自本机，可免令牌执行系统级操作。'
      setState({ ok: true, message })
      if (!quiet) toast({ title: '管理访问已解锁', description: message, variant: 'success' })
      onVerified?.()
    } catch {
      setState({ ok: false, message: '无法连接到后端服务器' })
      if (!quiet) toast({ title: '验证失败', description: '无法连接到后端服务器', variant: 'error' })
    } finally {
      setChecking(false)
    }
  }, [onVerified])

  useEffect(() => {
    if (token) void verify(token, true)
    // Only validate the restored session token on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const clear = () => {
    setToken('')
    setAdminSessionToken('')
    setState(null)
    toast({ title: '已清除本标签页的管理令牌' })
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="p-2 bg-amber-500/10 rounded-lg">
            <ShieldAlert className="w-5 h-5 text-amber-600" />
          </div>
          <div>
            <CardTitle>系统管理访问</CardTitle>
            <CardDescription>
              本机免令牌；从其它设备管理设置、备份、SwanLab 或 Skills 时，需要后端 ADMIN_TOKEN
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-col sm:flex-row gap-2">
          <div className="relative flex-1">
            <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              type={showToken ? 'text' : 'password'}
              className="pl-9 pr-10"
              placeholder="远程访问时输入 ADMIN_TOKEN；本机可留空"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void verify(token)
              }}
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="absolute right-1 top-1/2 -translate-y-1/2"
              onClick={() => setShowToken((value) => !value)}
              aria-label={showToken ? '隐藏管理令牌' : '显示管理令牌'}
            >
              {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </Button>
          </div>
          <Button onClick={() => void verify(token)} disabled={checking}>
            {checking ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <CheckCircle2 className="w-4 h-4 mr-2" />}
            保存并验证
          </Button>
          <Button variant="outline" onClick={clear} disabled={checking || (!token && !state)}>
            <Trash2 className="w-4 h-4 mr-2" />
            清除
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          令牌仅保存在当前浏览器标签页的 sessionStorage，关闭标签页后自动清除，不会写入项目数据库。
        </p>
        {state && (
          <div className={`p-3 rounded-lg text-sm ${state.ok ? 'bg-green-500/10 text-green-600' : 'bg-red-500/10 text-red-600'}`}>
            {state.message}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
