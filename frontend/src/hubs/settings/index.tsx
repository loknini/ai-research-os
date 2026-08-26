import { useState, useEffect, useCallback, useRef, type ChangeEvent } from 'react'
import { Header } from '@/components/layout/header'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/utils'
import { toast } from '@/components/ui/toast'
import SkillManager from './SkillManager'
import MemoryManager from './MemoryManager'
import RagSettingsManager from './RagSettingsManager'
import {
  Key,
  TestTube,
  Save,
  ExternalLink,
  CheckCircle2,
  XCircle,
  Loader2,
  FunctionSquare,
  Eye,
  EyeOff,
  Bot,
  RefreshCw,
  Database,
  Download,
  Upload,
  FileSearch,
  Plug,
  Puzzle
} from 'lucide-react'

interface SwanLabConfig {
  enabled: boolean
  apiUrl: string
  autoSync: boolean
  apiKeyConfigured: boolean
}

interface LLMConfig {
  baseUrl: string
  apiKeyMasked: string
  apiKeyConfigured: boolean
  model: string
  temperature: number
  maxTokens: number
  timeout: number
  httpPath: string
}

type SettingsTab = 'general' | 'integrations' | 'extensions' | 'rag'
const VALID_TABS: SettingsTab[] = ['general', 'integrations', 'extensions', 'rag']

const LLM_PRESETS = [
  { name: 'Agnes AI (免费)', baseUrl: 'https://apihub.agnes-ai.com/v1', model: '', keyHint: '在 Agnes 控制台获取 sk- 开头的 Key，然后点「获取模型」选择具体模型' },
  { name: '硅基流动', baseUrl: 'https://api.siliconflow.cn/v1', model: '', keyHint: '在 siliconflow.cn 获取 sk- 开头的 Key，然后点「获取模型」选择具体模型' },
  { name: '智谱 BigModel', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: '', keyHint: '在 bigmodel.cn 获取 Key（glm-4-flash 免费），然后点「获取模型」选择' },
  { name: 'Ollama (本地)', baseUrl: 'http://localhost:11434/v1', model: '', keyHint: '本地运行，Key 填 ollama 即可，然后点「获取模型」自动读取本机模型' },
]

export default function SettingsHub() {
  const [swanlabConfig, setSwanlabConfig] = useState<SwanLabConfig | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [apiUrl, setApiUrl] = useState('https://api.swanlab.cn/api')
  const [enabled, setEnabled] = useState(false)
  const [autoSync, setAutoSync] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  
  // SimpleTex Token 配置
  const [simpletexToken, setSimpletexToken] = useState('')
  const [showToken, setShowToken] = useState(false)
  const [isSavingToken, setIsSavingToken] = useState(false)

  // 联网搜索（web_search 技能）配置：BOCHA_API_KEY + WEB_SEARCH_PROVIDER
  const [bochaApiKey, setBochaApiKey] = useState('')
  const [showBochaKey, setShowBochaKey] = useState(false)
  const [bochaConfigured, setBochaConfigured] = useState(false)
  const [bochaMasked, setBochaMasked] = useState('')
  const [webSearchProvider, setWebSearchProvider] = useState('duckduckgo')
  const [isSavingBocha, setIsSavingBocha] = useState(false)
  const [bochaStatus, setBochaStatus] = useState<{ success: boolean; message: string } | null>(null)

  // 数据备份与迁移
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isExporting, setIsExporting] = useState(false)
  const [isImporting, setIsImporting] = useState(false)
  const [backupStatus, setBackupStatus] = useState<{ success: boolean; message: string } | null>(null)

  // LLM API 配置
  const [llmConfig, setLlmConfig] = useState<LLMConfig | null>(null)
  const [llmBaseUrl, setLlmBaseUrl] = useState('')
  const [llmApiKey, setLlmApiKey] = useState('')
  const [llmModel, setLlmModel] = useState('')
  const [showLlmKey, setShowLlmKey] = useState(false)
  const [llmSaving, setLlmSaving] = useState(false)
  const [llmTesting, setLlmTesting] = useState(false)
  const [llmTestResult, setLlmTestResult] = useState<{ success: boolean; message: string } | null>(null)
  // 可用模型列表（从接口拉取，用于模型名下拉）
  const [llmModels, setLlmModels] = useState<string[]>([])
  const [llmModelsLoading, setLlmModelsLoading] = useState(false)
  const [llmModelsError, setLlmModelsError] = useState<string | null>(null)

  // 设置分类标签（支持 hash 驱动：#/rag → rag tab）
  const [activeTab, setActiveTab] = useState<SettingsTab>(() => {
    const hash = window.location.hash.replace('#', '')
    return VALID_TABS.includes(hash as SettingsTab) ? (hash as SettingsTab) : 'general'
  })
  const SETTINGS_TABS: { id: SettingsTab; label: string; icon: React.ElementType }[] = [
    { id: 'general', label: '模型与 API', icon: Bot },
    { id: 'integrations', label: '集成服务', icon: Plug },
    { id: 'extensions', label: '扩展能力', icon: Puzzle },
    { id: 'rag', label: 'RAG 文档检索', icon: FileSearch },
  ]

  // 切换 tab：同步更新 hash（replaceState 不产生历史条目，避免后退栈污染）
  const changeTab = useCallback((tab: SettingsTab) => {
    setActiveTab(tab)
    history.replaceState(null, '', `#${tab}`)
  }, [])

  // 监听 hashchange：浏览器前进/后退或外部跳转（如 ChatHub 的「前往设置」）时同步 tab
  useEffect(() => {
    const onHashChange = () => {
      const hash = window.location.hash.replace('#', '')
      if (VALID_TABS.includes(hash as SettingsTab)) {
        setActiveTab(hash as SettingsTab)
      }
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const loadLlmConfig = useCallback(async () => {
    try {
      const response = await fetch('/api/settings/llm')
      if (response.ok) {
        const data = await response.json()
        if (data.success && data.config) {
          setLlmConfig(data.config)
          setLlmBaseUrl(data.config.baseUrl || '')
          setLlmModel(data.config.model || '')
        }
      }
    } catch (error) {
      console.error('Failed to load LLM config:', error)
    }
  }, [])

  const handleLlmTest = async () => {
    setLlmTesting(true)
    setLlmTestResult(null)
    try {
      const response = await fetch('/api/settings/llm/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          baseUrl: llmBaseUrl,
          apiKey: llmApiKey || undefined, // 留空则用已保存的 key
          model: llmModel
        })
      })
      const data = await response.json()
      setLlmTestResult(data)
      toast({
        title: data.success ? '连接成功' : '连接失败',
        description: data.message,
        variant: data.success ? 'success' : 'error'
      })
    } catch (error) {
      console.error('LLM test error:', error)
      setLlmTestResult({ success: false, message: '无法连接到后端服务器' })
      toast({ title: '测试失败', description: '无法连接到后端服务器', variant: 'error' })
    } finally {
      setLlmTesting(false)
    }
  }

  const handleLlmSave = async () => {
    if (!llmBaseUrl.trim() || !llmModel.trim()) {
      toast({ title: 'Base URL 和模型名称不能为空', variant: 'error' })
      return
    }
    setLlmSaving(true)
    try {
      const response = await fetch('/api/settings/llm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          baseUrl: llmBaseUrl,
          apiKey: llmApiKey, // 空字符串 = 沿用已保存的 key
          model: llmModel
        })
      })
      const data = await response.json()
      if (data.success) {
        toast({ title: '配置已保存并立即生效', description: data.message, variant: 'success' })
        setLlmApiKey('')
        setLlmTestResult(null)
        loadLlmConfig()
      } else {
        toast({ title: '保存失败', description: data.message, variant: 'error' })
      }
    } catch (error) {
      console.error('LLM save error:', error)
      toast({ title: '保存失败', description: '无法连接到后端服务器', variant: 'error' })
    } finally {
      setLlmSaving(false)
    }
  }

  // 保存联网搜索（web_search 技能）集成配置
  const handleSaveBocha = async () => {
    if (!bochaApiKey.trim() && !webSearchProvider.trim()) {
      toast({ title: '请至少填写一项', variant: 'error' })
      return
    }
    setIsSavingBocha(true)
    setBochaStatus(null)
    try {
      const response = await fetch('/api/settings/integration', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bochaApiKey: bochaApiKey, // 空字符串 = 沿用已保存的 key
          webSearchProvider: webSearchProvider
        })
      })
      const data = await response.json()
      setBochaStatus({ success: data.success, message: data.message })
      if (data.success) {
        toast({ title: '集成配置已保存', description: data.message, variant: 'success' })
        setBochaApiKey('')
        loadIntegrationConfig()
      } else {
        toast({ title: '保存失败', description: data.message, variant: 'error' })
      }
    } catch (error) {
      console.error('Save integration config error:', error)
      toast({ title: '保存失败', description: '无法连接到后端服务器', variant: 'error' })
    } finally {
      setIsSavingBocha(false)
    }
  }

  // 从 OpenAI 兼容的 /models 接口拉取可用模型列表
  const handleFetchModels = async () => {
    if (!llmBaseUrl.trim()) {
      toast({ title: '请先填写 Base URL', variant: 'error' })
      return
    }
    setLlmModelsLoading(true)
    setLlmModelsError(null)
    try {
      const qs = new URLSearchParams({
        baseUrl: llmBaseUrl,
        apiKey: llmApiKey || '',
      })
      const response = await fetch(`/api/settings/llm/models?${qs.toString()}`)
      const data = await response.json()
      if (data.success && Array.isArray(data.models) && data.models.length > 0) {
        setLlmModels(data.models)
        // 自动填充：当前模型名为空或不在列表里时，填入拉到的第一个真实模型名。
        setLlmModel(prev => {
          const trimmed = prev.trim()
          if (!trimmed || !data.models.includes(trimmed)) {
            return data.models[0]
          }
          return prev
        })
        toast({
          title: '已读取模型列表',
          description: `共 ${data.models.length} 个可用模型，已自动填入：${data.models[0]}`,
          variant: 'success'
        })
      } else {
        setLlmModelsError(data.message || '未找到可用模型')
        toast({ title: '读取失败', description: data.message || '未找到可用模型', variant: 'error' })
      }
    } catch (error) {
      setLlmModelsError('无法连接到后端服务器')
      toast({ title: '读取失败', description: '无法连接到后端服务器', variant: 'error' })
    } finally {
      setLlmModelsLoading(false)
    }
  }

  // 加载配置
  const loadConfig = useCallback(async () => {
    try {
      const response = await fetch('/api/swanlab/config')
      if (response.ok) {
        const data = await response.json()
        if (data.success && data.config) {
          setSwanlabConfig(data.config)
          setApiUrl(data.config.apiUrl || 'https://api.swanlab.cn/api')
          setEnabled(data.config.enabled || false)
          setAutoSync(data.config.autoSync || false)
        }
      }
    } catch (error) {
      console.error('Failed to load SwanLab config:', error)
    }
  }, [])

  // 加载集成服务配置（联网搜索）
  const loadIntegrationConfig = useCallback(async () => {
    try {
      const response = await fetch('/api/settings/integration')
      if (response.ok) {
        const data = await response.json()
        if (data.success && data.config) {
          setBochaConfigured(!!data.config.bochaConfigured)
          setBochaMasked(data.config.bochaApiKeyMasked || '')
          setWebSearchProvider(data.config.webSearchProvider || 'duckduckgo')
        }
      }
    } catch (error) {
      console.error('Failed to load integration config:', error)
    }
  }, [])

  useEffect(() => {
    loadConfig()
    loadLlmConfig()
    loadIntegrationConfig()
  }, [loadConfig, loadLlmConfig, loadIntegrationConfig])

  // 测试连接
  const handleTestConnection = async () => {
    if (!apiKey.trim()) {
      toast({ title: '请输入 API Key', variant: 'error' })
      return
    }

    setIsTesting(true)
    setTestResult(null)

    try {
      const response = await fetch('/api/swanlab/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ apiKey, apiUrl })
      })

      if (response.ok) {
        const data = await response.json()
        setTestResult(data)
        if (data.success) {
          toast({ title: '连接成功', description: data.message, variant: 'success' })
        } else {
          toast({ title: '连接失败', description: data.message, variant: 'error' })
        }
      }
    } catch (error) {
      console.error('Test connection error:', error)
      toast({ title: '测试失败', description: '无法连接到服务器', variant: 'error' })
    } finally {
      setIsTesting(false)
    }
  }

  // 保存配置
  const handleSaveConfig = async () => {
    if (!apiKey.trim() && enabled) {
      toast({ title: '请输入 API Key', variant: 'error' })
      return
    }

    setIsLoading(true)

    try {
      const response = await fetch('/api/swanlab/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          apiKey,
          apiUrl,
          enabled,
          autoSync
        })
      })

      if (response.ok) {
        const data = await response.json()
        if (data.success) {
          toast({ title: '配置保存成功', variant: 'success' })
          setApiKey('') // 清空输入框
          loadConfig() // 重新加载配置
        } else {
          toast({ title: '保存失败', description: data.error || data.message, variant: 'error' })
        }
      }
    } catch (error) {
      console.error('Save config error:', error)
      toast({ title: '保存失败', description: '无法连接到服务器', variant: 'error' })
    } finally {
      setIsLoading(false)
    }
  }

  // 导出备份：请求 /api/backup/export 拿到 zip 字节流，触发浏览器下载
  const handleExportBackup = async () => {
    setIsExporting(true)
    setBackupStatus(null)
    try {
      const resp = await fetch('/api/backup/export', { method: 'POST' })
      if (!resp.ok) {
        let msg = `导出失败（HTTP ${resp.status}）`
        try {
          const data = await resp.json()
          if (data && data.message) msg = data.message
        } catch {
          // 忽略解析失败，使用默认错误信息
        }
        setBackupStatus({ success: false, message: msg })
        toast({ title: '导出失败', description: msg, variant: 'error' })
        return
      }
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const disposition = resp.headers.get('Content-Disposition') || ''
      const nameMatch = disposition.match(/filename="?([^";]+)"?/)
      a.download = nameMatch ? nameMatch[1] : `airos-backup-${Date.now()}.zip`
      a.href = url
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      setBackupStatus({ success: true, message: '备份已导出并开始下载' })
      toast({ title: '导出成功', description: '备份包已开始下载', variant: 'success' })
    } catch (error) {
      console.error('Export backup error:', error)
      setBackupStatus({ success: false, message: '无法连接到后端服务器' })
      toast({ title: '导出失败', description: '无法连接到后端服务器', variant: 'error' })
    } finally {
      setIsExporting(false)
    }
  }

  // 导入备份：把选中的 zip 通过 FormData 发给 /api/backup/import
  const handleImportFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // 允许重复选择同一文件
    if (!file) return
    setIsImporting(true)
    setBackupStatus(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const resp = await fetch('/api/backup/import', { method: 'POST', body: formData })
      const data = await resp.json()
      if (data && data.success) {
        const count = Array.isArray(data.imported_entries) ? data.imported_entries.length : 0
        const note = data.note ? `（${data.note}）` : ''
        setBackupStatus({ success: true, message: `导入成功，已导入 ${count} 项${note}` })
        toast({ title: '导入成功', description: data.note || '数据已恢复', variant: 'success' })
      } else {
        const msg = (data && data.message) || '导入失败'
        setBackupStatus({ success: false, message: msg })
        toast({ title: '导入失败', description: msg, variant: 'error' })
      }
    } catch (error) {
      console.error('Import backup error:', error)
      setBackupStatus({ success: false, message: '无法连接到后端服务器' })
      toast({ title: '导入失败', description: '无法连接到后端服务器', variant: 'error' })
    } finally {
      setIsImporting(false)
    }
  }

  return (
    <div className="flex flex-col h-screen">
      <Header
        title="设置"
        description="配置系统集成和偏好设置"
      />

      <div className="flex-1 flex flex-col overflow-hidden">
        {/* 分类标签 */}
        <div className="px-6 pt-4 border-b border-border/50 shrink-0">
          <div className="max-w-4xl mx-auto flex flex-wrap gap-1">
            {SETTINGS_TABS.map((t) => {
              const Icon = t.icon
              const active = activeTab === t.id
              return (
                <button
                  key={t.id}
                  onClick={() => changeTab(t.id)}
                  className={cn(
                    'flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-medium transition-colors',
                    active
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                  )}
                >
                  <Icon className="w-4 h-4" />
                  {t.label}
                </button>
              )
            })}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-4xl mx-auto space-y-6">
          {/* LLM API 配置 */}
          {activeTab === 'general' && (<>
          <Card>
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="p-2 bg-violet-500/10 rounded-lg">
                  <Bot className="w-5 h-5 text-violet-500" />
                </div>
                <div>
                  <CardTitle>LLM API 配置</CardTitle>
                  <CardDescription>论文总结、Chat、多 Agent 协作依赖此配置（OpenAI 兼容接口）</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* 当前状态 */}
              <div className="flex items-center gap-4 p-4 bg-muted rounded-lg">
                <span className="text-sm font-medium">当前状态:</span>
                {llmConfig?.apiKeyConfigured ? (
                  <Badge className="bg-green-500/10 text-green-600">
                    <CheckCircle2 className="w-3 h-3 mr-1" />
                    已配置 · {llmConfig.model}
                  </Badge>
                ) : (
                  <Badge variant="secondary">
                    <XCircle className="w-3 h-3 mr-1" />
                    未配置
                  </Badge>
                )}
                {llmConfig?.apiKeyConfigured && (
                  <span className="text-xs text-muted-foreground ml-auto">
                    Key: {llmConfig.apiKeyMasked}
                  </span>
                )}
              </div>

              {/* 预设方案 */}
              <div className="space-y-2">
                <label className="text-sm font-medium">快速填充预设方案</label>
                <div className="flex flex-wrap gap-2">
                  {LLM_PRESETS.map((preset) => (
                    <Button
                      key={preset.name}
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setLlmBaseUrl(preset.baseUrl)
                        setLlmModel(preset.model)
                        setLlmTestResult(null)
                        toast({ title: `已填充 ${preset.name}`, description: preset.keyHint, variant: 'success' })
                      }}
                    >
                      {preset.name}
                    </Button>
                  ))}
                </div>
              </div>

              {/* Base URL */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Base URL</label>
                <Input
                  placeholder="例如 https://api.siliconflow.cn/v1"
                  value={llmBaseUrl}
                  onChange={(e) => setLlmBaseUrl(e.target.value)}
                />
              </div>

              {/* API Key */}
              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center gap-2">
                  <Key className="w-4 h-4" />
                  API Key
                </label>
                <div className="relative">
                  <Input
                    type={showLlmKey ? 'text' : 'password'}
                    placeholder={llmConfig?.apiKeyConfigured ? '已配置 (留空则沿用，输入新值可替换)' : '请输入 API Key'}
                    value={llmApiKey}
                    onChange={(e) => setLlmApiKey(e.target.value)}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    className="absolute right-2 top-1/2 -translate-y-1/2"
                    onClick={() => setShowLlmKey(!showLlmKey)}
                  >
                    {showLlmKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </Button>
                </div>
              </div>

              {/* 模型 */}
              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center gap-2">
                  <Bot className="w-4 h-4" />
                  模型名称
                </label>
                <div className="flex gap-2">
                  <Input
                    list="llm-model-list"
                    placeholder="点击右侧「获取模型」拉取，或手动输入模型名"
                    value={llmModel}
                    onChange={(e) => setLlmModel(e.target.value)}
                  />
                  <Button
                    variant="outline"
                    onClick={handleFetchModels}
                    disabled={llmModelsLoading || !llmBaseUrl.trim()}
                  >
                    {llmModelsLoading ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        获取中...
                      </>
                    ) : (
                      <>
                        <RefreshCw className="w-4 h-4 mr-2" />
                        获取模型
                      </>
                    )}
                  </Button>
                </div>
                <datalist id="llm-model-list">
                  {llmModels.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
                {llmModelsError && (
                  <p className="text-xs text-red-600">{llmModelsError}</p>
                )}
                {llmModels.length > 0 && !llmModelsError && (
                  <p className="text-xs text-muted-foreground">
                    已从接口读取 {llmModels.length} 个模型，点击输入框可下拉选择；也可直接输入其它模型名。
                  </p>
                )}
              </div>

              {/* 测试和保存 */}
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={handleLlmTest}
                  disabled={llmTesting || !llmBaseUrl.trim()}
                >
                  {llmTesting ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      测试中...
                    </>
                  ) : (
                    <>
                      <TestTube className="w-4 h-4 mr-2" />
                      测试连接
                    </>
                  )}
                </Button>
                <Button onClick={handleLlmSave} disabled={llmSaving}>
                  {llmSaving ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      保存中...
                    </>
                  ) : (
                    <>
                      <Save className="w-4 h-4 mr-2" />
                      保存配置
                    </>
                  )}
                </Button>
              </div>

              {/* 测试结果 */}
              {llmTestResult && (
                <div className={`p-3 rounded-lg text-sm ${
                  llmTestResult.success ? 'bg-green-500/10 text-green-600' : 'bg-red-500/10 text-red-600'
                }`}>
                  <div className="flex items-center gap-2">
                    {llmTestResult.success ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                    {llmTestResult.message}
                  </div>
                </div>
              )}

              <p className="text-xs text-muted-foreground">
                保存后立即生效，无需重启；配置会同时写入项目根目录 .env，重启后端后依然有效。
              </p>
            </CardContent>
          </Card>

          </>)}

          {/* ============ 集成服务 ============ */}
          {activeTab === 'integrations' && (<>
          {/* SwanLab 集成设置 */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="p-2 bg-blue-500/10 rounded-lg">
                  <TestTube className="w-5 h-5 text-blue-500" />
                </div>
                <div>
                  <CardTitle>SwanLab 集成</CardTitle>
                  <CardDescription>配置 SwanLab 实验追踪平台集成</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* 当前状态 */}
              <div className="flex items-center gap-4 p-4 bg-muted rounded-lg">
                <span className="text-sm font-medium">当前状态:</span>
                {swanlabConfig?.enabled && swanlabConfig?.apiKeyConfigured ? (
                  <Badge className="bg-green-500/10 text-green-600">
                    <CheckCircle2 className="w-3 h-3 mr-1" />
                    已配置
                  </Badge>
                ) : (
                  <Badge variant="secondary">
                    <XCircle className="w-3 h-3 mr-1" />
                    未配置
                  </Badge>
                )}
                {swanlabConfig?.enabled && swanlabConfig?.apiKeyConfigured && (
                  <a
                    href="https://swanlab.cn"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ml-auto flex items-center gap-1 text-sm text-blue-500 hover:underline"
                  >
                    访问 SwanLab <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>

              {/* API Key 输入 */}
              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center gap-2">
                  <Key className="w-4 h-4" />
                  API Key
                </label>
                <Input
                  type="password"
                  placeholder={swanlabConfig?.apiKeyConfigured ? '已配置 (输入新值可修改)' : '请输入 SwanLab API Key'}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  在 <a href="https://swanlab.cn/settings" target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">SwanLab 设置页面</a> 获取 API Key
                </p>
              </div>

              {/* API URL */}
              <div className="space-y-2">
                <label className="text-sm font-medium">API URL</label>
                <Input
                  placeholder="https://api.swanlab.cn/api"
                  value={apiUrl}
                  onChange={(e) => setApiUrl(e.target.value)}
                />
              </div>

              {/* 选项 */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="enabled"
                    checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                    className="rounded border-gray-300"
                  />
                  <label htmlFor="enabled" className="text-sm">启用 SwanLab 集成</label>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="autoSync"
                    checked={autoSync}
                    onChange={(e) => setAutoSync(e.target.checked)}
                    className="rounded border-gray-300"
                  />
                  <label htmlFor="autoSync" className="text-sm">自动同步实验数据</label>
                </div>
              </div>

              {/* 测试和保存按钮 */}
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={handleTestConnection}
                  disabled={isTesting || !apiKey.trim()}
                >
                  {isTesting ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      测试中...
                    </>
                  ) : (
                    <>
                      <TestTube className="w-4 h-4 mr-2" />
                      测试连接
                    </>
                  )}
                </Button>
                <Button
                  onClick={handleSaveConfig}
                  disabled={isLoading}
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      保存中...
                    </>
                  ) : (
                    <>
                      <Save className="w-4 h-4 mr-2" />
                      保存配置
                    </>
                  )}
                </Button>
              </div>

              {/* 测试结果 */}
              {testResult && (
                <div className={`p-3 rounded-lg text-sm ${
                  testResult.success ? 'bg-green-500/10 text-green-600' : 'bg-red-500/10 text-red-600'
                }`}>
                  {testResult.success ? (
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4" />
                      {testResult.message}
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <XCircle className="w-4 h-4" />
                      {testResult.message}
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {/* 使用说明 */}
          <Card>
            <CardHeader>
              <CardTitle>使用说明</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm text-muted-foreground">
              <div>
                <p className="font-medium text-foreground mb-2">1. 获取 API Key</p>
                <p>访问 <a href="https://swanlab.cn" target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">SwanLab</a> 并登录您的账号，在设置页面生成 API Key。</p>
              </div>
              <div>
                <p className="font-medium text-foreground mb-2">2. 配置集成</p>
                <p>在上方的表单中输入 API Key，点击"测试连接"验证配置是否正确，然后点击"保存配置"。</p>
              </div>
              <div>
                <p className="font-medium text-foreground mb-2">3. 同步实验</p>
                <p>配置完成后，您可以在实验管理页面将实验数据同步到 SwanLab，或使用自动同步功能。</p>
              </div>
            </CardContent>
          </Card>

          {/* SimpleTex Token 配置 */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FunctionSquare className="w-5 h-5" />
                公式识别 (SimpleTex)
              </CardTitle>
              <CardDescription>
                配置 SimpleTex API Token 以使用公式识别功能
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">User Access Token (UAT)</label>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <Input
                      type={showToken ? 'text' : 'password'}
                      placeholder="输入 SimpleTex UAT Token"
                      value={simpletexToken}
                      onChange={(e) => setSimpletexToken(e.target.value)}
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      className="absolute right-2 top-1/2 -translate-y-1/2"
                      onClick={() => setShowToken(!showToken)}
                    >
                      {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </Button>
                  </div>
                  <Button
                    onClick={async () => {
                      if (!simpletexToken.trim()) {
                        toast({ title: '请输入 Token', variant: 'error' })
                        return
                      }
                      setIsSavingToken(true)
                      // 保存到 localStorage
                      localStorage.setItem('simpletex_token', simpletexToken)
                      toast({ title: 'Token 已保存', variant: 'success' })
                      setIsSavingToken(false)
                    }}
                    disabled={isSavingToken}
                  >
                    {isSavingToken ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
                    保存
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Token 仅存储在本地浏览器中，不会上传到服务器
                </p>
              </div>

              <div className="space-y-2 text-sm text-muted-foreground">
                <p className="font-medium text-foreground">如何获取 Token：</p>
                <ol className="list-decimal list-inside space-y-1">
                  <li>访问 <a href="https://simpletex.cn" target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">simpletex.cn</a> 并注册账号</li>
                  <li>进入用户中心 → 用户授权令牌</li>
                  <li>创建新的 UAT Token</li>
                  <li>复制 Token 并粘贴到上方输入框</li>
                </ol>
                <p className="text-xs mt-2">
                  免费额度：轻量模型每日 2000 次，标准模型每日 500 次
                </p>
              </div>
            </CardContent>
          </Card>

          {/* 联网搜索（web_search 技能）配置 */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="p-2 bg-sky-500/10 rounded-lg">
                  <FileSearch className="w-5 h-5 text-sky-500" />
                </div>
                <div>
                  <CardTitle>联网搜索 (Web Search)</CardTitle>
                  <CardDescription>为 Chat Agent 与多 Agent 管线提供联网搜索能力（web_search 技能）。默认使用免 Key 的 DuckDuckGo，开箱即用；可选项填 BOCHA Key 获得更高质量结果。</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* 当前状态 */}
              <div className="flex items-center gap-4 p-4 bg-muted rounded-lg">
                <span className="text-sm font-medium">当前状态:</span>
                {bochaConfigured ? (
                  <Badge className="bg-green-500/10 text-green-600">
                    <CheckCircle2 className="w-3 h-3 mr-1" />
                    增强已启用 · {webSearchProvider}
                  </Badge>
                ) : (
                  <Badge variant="secondary">
                    <CheckCircle2 className="w-3 h-3 mr-1" />
                    默认 DuckDuckGo 免 Key 联网（已可用）
                  </Badge>
                )}
                {bochaConfigured && bochaMasked && (
                  <span className="text-xs text-muted-foreground ml-auto">
                    Key: {bochaMasked}
                  </span>
                )}
              </div>

              {/* BOCHA_API_KEY */}
              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center gap-2">
                  <Key className="w-4 h-4" />
                  BOCHA API Key（可选增强）
                </label>
                <div className="relative">
                  <Input
                    type={showBochaKey ? 'text' : 'password'}
                    placeholder={bochaConfigured ? '已配置 (输入新值可替换)' : '请输入博查 BOCHA_API_KEY'}
                    value={bochaApiKey}
                    onChange={(e) => setBochaApiKey(e.target.value)}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    className="absolute right-2 top-1/2 -translate-y-1/2"
                    onClick={() => setShowBochaKey(!showBochaKey)}
                  >
                    {showBochaKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  可选增强项：在 <a href="https://bochaai.com" target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">bochaai.com</a> 注册可领 1000 次免费额度。不填也能用——web_search 默认走免 Key 的 DuckDuckGo 实时联网；填了可获得博查更高质量（含大模型摘要）的结果。
                </p>
              </div>

              {/* WEB_SEARCH_PROVIDER */}
              <div className="space-y-2">
                <label className="text-sm font-medium">搜索提供商</label>
                <select
                  value={webSearchProvider}
                  onChange={(e) => setWebSearchProvider(e.target.value)}
                  className="w-full h-10 rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <option value="duckduckgo">duckduckgo（默认，免 Key 实时联网）</option>
                  <option value="bocha">bocha（博查，需 Key，更高质量）</option>
                  <option value="wikipedia">wikipedia（零密钥，仅百科类内容）</option>
                </select>
              </div>

              {/* 保存 */}
              <div className="flex gap-3">
                <Button onClick={handleSaveBocha} disabled={isSavingBocha}>
                  {isSavingBocha ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      保存中...
                    </>
                  ) : (
                    <>
                      <Save className="w-4 h-4 mr-2" />
                      保存配置
                    </>
                  )}
                </Button>
              </div>

              {bochaStatus && (
                <div className={`p-3 rounded-lg text-sm ${
                  bochaStatus.success ? 'bg-green-500/10 text-green-600' : 'bg-red-500/10 text-red-600'
                }`}>
                  <div className="flex items-center gap-2">
                    {bochaStatus.success ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                    {bochaStatus.message}
                  </div>
                </div>
              )}

              <p className="text-xs text-muted-foreground">
                保存后当前 worker 立即生效；若以多 worker 启动（默认 8 个），其它 worker 需重启后端后同步。配置同时写入项目根 .env，重启后仍有效。
              </p>
            </CardContent>
          </Card>

          </>)}

          {/* ============ 扩展能力 ============ */}
          {activeTab === 'extensions' && (<>
          {/* 技能管理 */}
          <SkillManager />

          {/* 长期记忆 */}
          <MemoryManager />

          </>)}

          {/* 数据备份与迁移归入「集成服务」 */}
          {activeTab === 'integrations' && (<>
          {/* 数据备份与迁移 */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="p-2 bg-emerald-500/10 rounded-lg">
                  <Database className="w-5 h-5 text-emerald-500" />
                </div>
                <div>
                  <CardTitle>数据备份与迁移</CardTitle>
                  <CardDescription>导出整个数据目录为备份包，或导入备份包恢复 / 迁移到新设备</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-3">
                <Button
                  variant="outline"
                  onClick={handleExportBackup}
                  disabled={isExporting}
                >
                  {isExporting ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      导出中...
                    </>
                  ) : (
                    <>
                      <Download className="w-4 h-4 mr-2" />
                      导出备份
                    </>
                  )}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isImporting}
                >
                  {isImporting ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      导入中...
                    </>
                  ) : (
                    <>
                      <Upload className="w-4 h-4 mr-2" />
                      导入备份
                    </>
                  )}
                </Button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".zip"
                  className="hidden"
                  onChange={handleImportFile}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                导出会打包 papers / experiments / software / knowledge 以及数据库，并自动剔除缓存与历史残留目录；导入前会自动备份当前数据到 <code>.backup-时间戳</code> 目录。
              </p>
              {backupStatus && (
                <div className={`p-3 rounded-lg text-sm ${
                  backupStatus.success ? 'bg-green-500/10 text-green-600' : 'bg-red-500/10 text-red-600'
                }`}>
                  <div className="flex items-center gap-2">
                    {backupStatus.success ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                    {backupStatus.message}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
          </>)}

          {/* ============ RAG 文档检索 ============ */}
          {activeTab === 'rag' && <RagSettingsManager />}
          </div>
        </div>
      </div>
    </div>
  )
}
