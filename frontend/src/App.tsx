import { useEffect, lazy, Suspense } from 'react'
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { Sidebar } from '@/components/layout/sidebar'
import { GlobalToastContainer } from '@/components/ui/toast'
import { ChatPanel } from '@/components/chat/chat-panel'
import { CommandPalette } from '@/components/search/command-palette'
import { useAppStore } from '@/stores/appStore'
import { Loader2 } from 'lucide-react'
import { applyTheme, useThemeStore } from '@/stores/themeStore'
import { GenerationWatcher } from '@/components/agent/generation-watcher'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { installApiMonitor } from '@/services/apiMonitor'
import { SpaceGate } from '@/components/SpaceGate'
import NotFound from '@/components/ui/not-found'

// 路由级代码分割：各 Hub 改为懒加载，缩小首屏包体
const Dashboard = lazy(() => import('@/hubs/dashboard'))
const PaperHub = lazy(() => import('@/hubs/paper'))
const LabHub = lazy(() => import('@/hubs/lab'))
const KnowledgeHub = lazy(() => import('@/hubs/knowledge'))
const TaskHub = lazy(() => import('@/hubs/task'))
const SettingsHub = lazy(() => import('@/hubs/settings'))
const ChatHub = lazy(() => import('@/hubs/chat'))
const FormulaHub = lazy(() => import('@/hubs/formula'))
const CitationHub = lazy(() => import('@/hubs/citation'))
const AgentRunsHub = lazy(() => import('@/hubs/agent-runs'))
const CronHub = lazy(() => import('@/hubs/cron'))

// 安装全局 fetch 监控：真实 /api 流量驱动侧边栏「后端状态」灯，
// 取代原先每 5 秒的 healthz 轮询（不再有常驻日志噪音与无谓外网探测）。
installApiMonitor()

// 应用挂载时只做一次存活检查，确定初始连接状态；之后由全局 fetch 监控维护。
function BackendHealthMonitor() {
  const { setConnected } = useAppStore()
  useEffect(() => {
    let alive = true
    fetch('/api/healthz', { headers: { Accept: 'application/json' } })
      .then((r) => {
        if (!alive) return
        setConnected(r.ok || r.status < 500)
      })
      .catch(() => {
        if (alive) setConnected(false)
      })
    return () => {
      alive = false
    }
  }, [setConnected])
  return null
}

// 主题同步：模式变化即应用到 <html>，system 模式下实时跟随系统偏好
function ThemeSync() {
  const mode = useThemeStore((s) => s.mode)
  useEffect(() => {
    applyTheme(mode)
  }, [mode])
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => {
      if (useThemeStore.getState().mode === 'system') applyTheme('system')
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  return null
}

// 路由懒加载时的占位
function RouteFallback() {
  return (
    <div className="h-full w-full flex items-center justify-center">
      <div className="flex flex-col items-center gap-3 text-muted-foreground">
        <Loader2 className="w-6 h-6 animate-spin" />
        <span className="text-sm">加载中…</span>
      </div>
    </div>
  )
}

function App() {
  return (
    <Router>
      <BackendHealthMonitor />
      <ThemeSync />
      <GenerationWatcher />
      <SpaceGate>
        <div className="flex h-screen">
          <Sidebar />
          <main className="flex-1 overflow-hidden">
            <ErrorBoundary>
              <Suspense fallback={<RouteFallback />}>
                <Routes>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/chat" element={<ChatHub />} />
                  <Route path="/paper" element={<PaperHub />} />
                  <Route path="/lab" element={<LabHub />} />
                  {/* 旧路由保留可直达：研发实验已合并进 /lab */}
                  <Route path="/software" element={<Navigate to="/lab" replace />} />
                  <Route path="/experiment" element={<Navigate to="/lab?tab=experiment" replace />} />
                  <Route path="/knowledge" element={<KnowledgeHub />} />
                  <Route path="/task" element={<TaskHub />} />
                  <Route path="/formula" element={<FormulaHub />} />
                  <Route path="/citation" element={<CitationHub />} />
                  <Route path="/agent-runs" element={<AgentRunsHub />} />
                  <Route path="/cron" element={<CronHub />} />
                  <Route path="/settings" element={<SettingsHub />} />
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </Suspense>
            </ErrorBoundary>
          </main>
          <GlobalToastContainer />
          <ChatPanel />
          <CommandPalette isGlobal={true} />
        </div>
      </SpaceGate>
    </Router>
  )
}

export default App
