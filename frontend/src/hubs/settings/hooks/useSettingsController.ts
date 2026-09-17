import { apiRequest, downloadBlob, uploadForm } from '@/services/api'
import React, { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react'
import { Bot, FileSearch, Plug, Puzzle } from 'lucide-react'
import { toast } from '@/components/ui/toast'

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
  embedModel?: string
  embedProvider?: string
  embedLocalModel?: string
  temperature: number
  maxTokens: number
  timeout: number
  httpPath: string
}

interface LocalEmbedModel {
  id: string
  path: string
  sizeMB: number
  downloaded: boolean
  incomplete?: boolean
}

interface BackupImportResponse {
  success: boolean
  imported_entries?: unknown[]
  note?: string
  message?: string
}

type SettingsTab = 'general' | 'integrations' | 'extensions' | 'rag'
const VALID_TABS: SettingsTab[] = ['general', 'integrations', 'extensions', 'rag']

export function useSettingsController() {
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
  const [modelPickerOpen, setModelPickerOpen] = useState(false)

  // ---- 嵌入模型配置（RAG 向量，全局单一；单空间单向量空间，不按源覆盖） ----
  const [embedProvider, setEmbedProvider] = useState('api')
  const [apiEmbedModel, setApiEmbedModel] = useState('')
  const [localModels, setLocalModels] = useState<LocalEmbedModel[]>([])
  const [localModelSel, setLocalModelSel] = useState('') // 已下载 id 或 '__custom'
  const [localModelCustom, setLocalModelCustom] = useState('')
  const [localModelsLoading, setLocalModelsLoading] = useState(false)
  const [embedResolveInfo, setEmbedResolveInfo] = useState<{ resolvable: boolean; reason: string; loaded: boolean } | null>(null)
  const [localEmbedError, setLocalEmbedError] = useState('')
  const [embedConfigured, setEmbedConfigured] = useState('')
  // ---- 本地模型后台下载状态（状态机：内存/DB 双写，刷新不丢） ----
  const [dlState, setDlState] = useState<{ state: string; sizeMB: number; error: string } | null>(null)
  const [dlTarget, setDlTarget] = useState('')

  // 本次下载/保存取用的本地模型 ID（下拉已下载优先，自定义次之）
  const embedDownloadTarget = useCallback(() => {
    if (localModelSel && localModelSel !== '__custom') return localModelSel
    return localModelCustom.trim()
  }, [localModelSel, localModelCustom])

  const fetchDlStatus = useCallback(async (model: string) => {
    if (!model) return null
    try {
      const r = await apiRequest(`/api/settings/embed-download-status?model=${encodeURIComponent(model)}`)
      const j = await r.json()
      if (j.success) {
        setDlState({ state: j.state, sizeMB: j.sizeMB || 0, error: j.error || '' })
        return j.state as string
      }
    } catch {
      /* 轮询失败忽略，下轮继续 */
    }
    return null
  }, [])

  const startEmbedDownload = useCallback(async () => {
    const target = embedDownloadTarget()
    if (!target) {
      toast({ title: '请先选择或填写本地嵌入模型', variant: 'error' })
      return
    }
    setDlTarget(target)
    setDlState({ state: 'downloading', sizeMB: 0, error: '' })
    try {
      const r = await apiRequest('/api/settings/embed-download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: target }),
      })
      const j = await r.json()
      if (!j.success) {
        if (j.activeModel) {
          // 单飞行：转去围观真正的进行中任务
          setDlTarget(j.activeModel)
          setDlState({ state: 'downloading', sizeMB: 0, error: '' })
          toast({ title: `已有下载进行中：${j.activeModel}，已切换查看`, variant: 'success' })
        } else {
          setDlState({ state: 'failed', sizeMB: 0, error: j.message || '提交失败' })
          toast({ title: '下载提交失败', description: j.message, variant: 'error' })
        }
      }
    } catch (e) {
      console.error(e)
      setDlState({ state: 'failed', sizeMB: 0, error: '无法连接到后端服务器' })
    }
  }, [embedDownloadTarget])

  // 下载中轮询 effect 见 loadLocalModels 定义之后（需引用它，避免 TDZ 报错）

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
      const response = await apiRequest('/api/settings/llm')
      if (response.ok) {
        const data = await response.json()
        if (data.success && data.config) {
          setLlmConfig(data.config)
          setLlmBaseUrl(data.config.baseUrl || '')
          setLlmModel(data.config.model || '')
          setEmbedProvider(data.config.embedProvider || 'api')
          setApiEmbedModel(data.config.embedModel || '')
          // 本地模型选中态由 loadLocalModels 按 configured 回填（需等已下载列表）
          const cfgLocal = (data.config.embedLocalModel || '').trim()
          if (cfgLocal) setLocalModelCustom((prev) => prev || cfgLocal)
        }
      }
    } catch (error) {
      console.error('Failed to load LLM config:', error)
    }
  }, [])

  // 已下载本地嵌入模型列表（只读扫描，不触发下载）
  const loadLocalModels = useCallback(async () => {
    setLocalModelsLoading(true)
    try {
      const response = await apiRequest('/api/settings/embed-local-models')
      if (response.ok) {
        const data = await response.json()
        if (data.success) {
          const list: LocalEmbedModel[] = data.models || []
          setLocalModels(list)
          setEmbedConfigured((data.configured || '').trim())
          setEmbedResolveInfo({ resolvable: !!data.resolvable, reason: data.reason || '', loaded: !!data.loaded })
          setLocalEmbedError((data.loadError || '').trim())
          const cfgLocal = (data.configured || '').trim()
          if (cfgLocal) {
            setLocalModelCustom((prev) => prev || cfgLocal)
            if (list.some((m) => m.id === cfgLocal)) setLocalModelSel(cfgLocal)
            else setLocalModelSel((prev) => prev || '__custom')
          } else if (list.length > 0) {
            setLocalModelSel((prev) => prev || list[0].id)
          }
        }
      }
    } catch (error) {
      console.error('Failed to load local embed models:', error)
    } finally {
      setLocalModelsLoading(false)
    }
  }, [])

  // 下载中轮询：完成/失败即停并刷新已下载列表。
  // T2 收敛：后台标签页暂停 + 30s 后退避到 5s（本地小文件 GET，不上 SSE）。
  useEffect(() => {
    if (!dlTarget || dlState?.state !== 'downloading') return
    let stopped = false
    let busy = false
    let ticks = 0
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      if (stopped || busy) return
      if (document.hidden) return // 后台页跳过本轮，重调度（不计数）
      busy = true
      try {
        ticks += 1
        const st = await fetchDlStatus(dlTarget)
        if (stopped) return
        if (st === 'ready') {
          toast({ title: '模型下载完成', variant: 'success' })
          loadLocalModels()
          // 若下载的正是当前配置（或尚未配置），解析提示同步变绿
          if (!embedConfigured || embedConfigured === dlTarget) {
            setEmbedResolveInfo((prev) => prev ? { ...prev, resolvable: true, reason: '已下载，可保存使用。' } : prev)
          }
          return // 终态：停轮询
        }
        if (st === 'failed') {
          toast({ title: '模型下载失败，可重试', variant: 'error' })
          return // 终态：停轮询
        }
      } finally {
        busy = false
      }
      if (!stopped) timer = setTimeout(tick, ticks >= 15 ? 5000 : 2000)
    }
    const onVis = () => {
      if (!document.hidden) void tick() // 回前台立刻补一次
    }
    document.addEventListener('visibilitychange', onVis)
    void tick()
    return () => {
      stopped = true
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [dlTarget, dlState?.state, embedConfigured, fetchDlStatus, loadLocalModels])

  // T1：切 Hub 回来后恢复下载轮询（组件挂载时查进行中的任务）
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await apiRequest('/api/settings/embed-download-active')
        const j = await r.json()
        if (!cancelled && j.success && j.active) {
          setDlTarget(j.active.model)
          setDlState({ state: 'downloading', sizeMB: j.active.sizeMB || 0, error: '' })
          toast({ title: `下载进行中：${j.active.model}，已恢复进度显示`, variant: 'success' })
        }
      } catch {
        /* 忽略，下载按钮仍可手动触发 */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const handleLlmTest = async () => {
    setLlmTesting(true)
    setLlmTestResult(null)
    try {
      const response = await apiRequest('/api/settings/llm/test', {
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
    // 本地嵌入模型取值：下拉已下载优先，自定义次之
    const effectiveLocalModel = embedProvider === 'local'
      ? (localModelSel && localModelSel !== '__custom'
          ? localModelSel
          : localModelCustom.trim())
      : ''
    if (embedProvider === 'local' && !effectiveLocalModel) {
      toast({ title: '请选择或填写本地嵌入模型', variant: 'error' })
      return
    }
    setLlmSaving(true)
    try {
      const response = await apiRequest('/api/settings/llm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          baseUrl: llmBaseUrl,
          apiKey: llmApiKey, // 空字符串 = 沿用已保存的 key
          model: llmModel,
          embedProvider,
          embedModel: embedProvider === 'api' ? apiEmbedModel : '',
          embedLocalModel: effectiveLocalModel,
        })
      })
      const data = await response.json()
      if (data.success) {
        toast({ title: '配置已保存并立即生效', description: data.message, variant: 'success' })
        setLlmApiKey('')
        setLlmTestResult(null)
        loadLlmConfig()
        loadLocalModels()
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
      const response = await apiRequest('/api/settings/integration', {
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
      const response = await apiRequest(`/api/settings/llm/models?${qs.toString()}`)
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
      const response = await apiRequest('/api/swanlab/config')
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
      const response = await apiRequest('/api/settings/integration')
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

  const reloadProtectedSettings = useCallback(() => {
    loadConfig()
    loadLlmConfig()
    loadIntegrationConfig()
    loadLocalModels()
  }, [loadConfig, loadLlmConfig, loadIntegrationConfig, loadLocalModels])

  useEffect(() => {
    reloadProtectedSettings()
  }, [reloadProtectedSettings])

  // 测试连接
  const handleTestConnection = async () => {
    if (!apiKey.trim()) {
      toast({ title: '请输入 API Key', variant: 'error' })
      return
    }

    setIsTesting(true)
    setTestResult(null)

    try {
      const response = await apiRequest('/api/swanlab/test', {
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
      const response = await apiRequest('/api/swanlab/config', {
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
      const { blob, response } = await downloadBlob('/api/backup/export', { method: 'POST' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const disposition = response.headers.get('Content-Disposition') || ''
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
      const data = await uploadForm<BackupImportResponse>('/api/backup/import', formData)
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

  return {
    SETTINGS_TABS, swanlabConfig, setSwanlabConfig, apiKey, setApiKey, apiUrl, setApiUrl, enabled, setEnabled, autoSync, setAutoSync, isLoading, setIsLoading, isTesting, setIsTesting, testResult, setTestResult, simpletexToken, setSimpletexToken, showToken, setShowToken, isSavingToken, setIsSavingToken, bochaApiKey, setBochaApiKey, showBochaKey, setShowBochaKey, bochaConfigured, setBochaConfigured, bochaMasked, setBochaMasked, webSearchProvider, setWebSearchProvider, isSavingBocha, setIsSavingBocha, bochaStatus, setBochaStatus, fileInputRef, isExporting, setIsExporting, isImporting, setIsImporting, backupStatus, setBackupStatus, llmConfig, setLlmConfig, llmBaseUrl, setLlmBaseUrl, llmApiKey, setLlmApiKey, llmModel, setLlmModel, showLlmKey, setShowLlmKey, llmSaving, setLlmSaving, llmTesting, setLlmTesting, llmTestResult, setLlmTestResult, llmModels, setLlmModels, llmModelsLoading, setLlmModelsLoading, llmModelsError, setLlmModelsError, modelPickerOpen, setModelPickerOpen, embedProvider, setEmbedProvider, apiEmbedModel, setApiEmbedModel, localModels, setLocalModels, localModelSel, setLocalModelSel, localModelCustom, setLocalModelCustom, localModelsLoading, setLocalModelsLoading, embedResolveInfo, setEmbedResolveInfo, localEmbedError, setLocalEmbedError, embedConfigured, setEmbedConfigured, dlState, setDlState, dlTarget, setDlTarget, embedDownloadTarget, fetchDlStatus, startEmbedDownload, activeTab, setActiveTab, changeTab, loadLlmConfig, loadLocalModels, handleLlmTest, handleLlmSave, handleSaveBocha, handleFetchModels, loadConfig, loadIntegrationConfig, reloadProtectedSettings, handleTestConnection, handleSaveConfig, handleExportBackup, handleImportFile
  }
}

export type SettingsController = ReturnType<typeof useSettingsController>
