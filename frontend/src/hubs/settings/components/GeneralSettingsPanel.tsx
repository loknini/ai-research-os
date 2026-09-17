import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import { cn } from '@/utils'
import {
  Bot, CheckCircle2, Download, Eye, EyeOff, Key, Loader2, RefreshCw,
  Save, TestTube, XCircle,
} from 'lucide-react'
import type { SettingsController } from '../hooks/useSettingsController'

const LLM_PRESETS = [
  { name: 'Agnes AI (免费)', baseUrl: 'https://apihub.agnes-ai.com/v1', model: '', keyHint: '在 Agnes 控制台获取 sk- 开头的 Key，然后点「获取模型」选择具体模型' },
  { name: '硅基流动', baseUrl: 'https://api.siliconflow.cn/v1', model: '', keyHint: '在 siliconflow.cn 获取 sk- 开头的 Key，然后点「获取模型」选择具体模型' },
  { name: '智谱 BigModel', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: '', keyHint: '在 bigmodel.cn 获取 Key（glm-4-flash 免费），然后点「获取模型」选择' },
  { name: 'Ollama (本地)', baseUrl: 'http://localhost:11434/v1', model: '', keyHint: '本地运行，Key 填 ollama 即可，然后点「获取模型」自动读取本机模型' },
]

interface PanelProps { settings: SettingsController }

export function GeneralSettingsPanel({ settings }: PanelProps) {
  const { llmConfig, llmBaseUrl, setLlmBaseUrl, llmApiKey, setLlmApiKey, llmModel, setLlmModel, showLlmKey, setShowLlmKey, llmSaving, llmTesting, llmTestResult, setLlmTestResult, llmModels, llmModelsLoading, llmModelsError, modelPickerOpen, setModelPickerOpen, embedProvider, setEmbedProvider, apiEmbedModel, setApiEmbedModel, localModels, localModelSel, setLocalModelSel, localModelCustom, setLocalModelCustom, localModelsLoading, embedResolveInfo, localEmbedError, dlState, embedDownloadTarget, startEmbedDownload, activeTab, handleLlmTest, handleLlmSave, handleFetchModels } = settings
  return (
    <>
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
                  <div className="relative flex-1">
                    <Input
                      placeholder="点击右侧「获取模型」拉取，或手动输入模型名"
                      value={llmModel}
                      onChange={(e) => setLlmModel(e.target.value)}
                      onFocus={() => llmModels.length > 0 && setModelPickerOpen(true)}
                      onBlur={() => setTimeout(() => setModelPickerOpen(false), 150)}
                    />
                    {modelPickerOpen && llmModels.length > 0 && (
                      <div className="absolute z-10 mt-1 w-full rounded-md border bg-popover shadow-lg max-h-60 overflow-auto">
                        {llmModels.map((m) => (
                          <button
                            key={m}
                            type="button"
                            onMouseDown={(e) => {
                              e.preventDefault()
                              setLlmModel(m)
                              setModelPickerOpen(false)
                            }}
                            className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent"
                          >
                            {m}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
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
                {llmModelsError && (
                  <p className="text-xs text-red-600">{llmModelsError}</p>
                )}
                {llmModels.length > 0 && !llmModelsError && (
                  <p className="text-xs text-muted-foreground">
                    已从接口读取 {llmModels.length} 个模型，点击输入框可查看全量 {llmModels.length} 个（扁平展示，不分组）；也可直接输入其它模型名。
                  </p>
                )}
              </div>

              {/* 嵌入模型（RAG 向量，全局单一配置） */}
              <div className="space-y-3 rounded-lg border border-border/60 p-4">
                <div>
                  <label className="text-sm font-medium">嵌入模型（RAG 文档检索用）</label>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    全空间共用同一向量空间，切换模型后建议重建索引；随下方「保存配置」一起保存，立即生效。
                  </p>
                </div>
                <div className="space-y-2">
                  <label className="text-sm text-muted-foreground">嵌入 Provider</label>
                  <select
                    value={embedProvider}
                    onChange={(e) => setEmbedProvider(e.target.value)}
                    className="w-full h-10 rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <option value="api">API（走上方 LLM 服务的 /v1/embeddings）</option>
                    <option value="local">本地模型（离线，需 GPU 或 CPU）</option>
                  </select>
                </div>
                {embedProvider === 'api' ? (
                  <div className="space-y-2">
                    <label className="text-sm text-muted-foreground">API 嵌入模型（可选）</label>
                    <Input
                      placeholder="留空则使用上面的对话模型名"
                      value={apiEmbedModel}
                      onChange={(e) => setApiEmbedModel(e.target.value)}
                    />
                  </div>
                ) : (
                  <div className="space-y-2">
                    <label className="text-sm text-muted-foreground">本地嵌入模型</label>
                    {localModels.length === 0 ? (
                      <Input
                        placeholder="如 Qwen/Qwen3-Embedding-0.6B（保存后可下载到 data/models/，~1.2GB）"
                        value={localModelCustom}
                        onChange={(e) => setLocalModelCustom(e.target.value)}
                        disabled={dlState?.state === 'downloading'}
                      />
                    ) : (
                      <>
                        <select
                          value={localModelSel}
                          onChange={(e) => setLocalModelSel(e.target.value)}
                          disabled={localModelsLoading || dlState?.state === 'downloading'}
                          title={dlState?.state === 'downloading' ? '下载进行中，暂勿切换模型' : undefined}
                          className="w-full h-10 rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
                        >
                          {localModels.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.downloaded && !m.incomplete
                                ? `${m.id}（已下载，${m.sizeMB} MB）`
                                : `${m.id}（下载不完整 ${m.sizeMB} MB，可续传）`}
                            </option>
                          ))}
                          <option value="__custom">手动输入 ModelScope ID 或本地目录…</option>
                        </select>
                        {localModelSel === '__custom' && (
                          <Input
                            placeholder="如 Qwen/Qwen3-Embedding-0.6B（保存后可下载到 data/models/，~1.2GB）"
                            value={localModelCustom}
                            onChange={(e) => setLocalModelCustom(e.target.value)}
                            disabled={dlState?.state === 'downloading'}
                          />
                        )}
                      </>
                    )}
                    {embedDownloadTarget() && !(
                      localModelSel && localModelSel !== '__custom'
                      && localModels.some((m) => m.id === localModelSel && m.downloaded && !m.incomplete)
                    ) && (
                      <div className="flex items-center gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={startEmbedDownload}
                          disabled={dlState?.state === 'downloading' || !embedDownloadTarget()}
                        >
                          {dlState?.state === 'downloading' ? (
                            <>
                              <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                              下载中…{dlState.sizeMB > 0 ? `已下 ${dlState.sizeMB} MB` : ''}（切 Hub 可离开，回来自动续显）
                            </>
                          ) : (
                            <>
                              <Download className="w-3.5 h-3.5 mr-1.5" />
                              下载模型
                            </>
                          )}
                        </Button>
                        {dlState?.state === 'failed' && (
                          <button
                            className="text-xs text-primary hover:underline"
                            onClick={startEmbedDownload}
                          >
                            重试
                          </button>
                        )}
                      </div>
                    )}
                    {embedResolveInfo && (
                      <p className={cn('text-xs', embedResolveInfo.resolvable ? 'text-green-600' : 'text-yellow-600')}>
                        {embedResolveInfo.loaded
                          ? '已加载进内存，可直接使用。'
                          : dlState?.state === 'failed'
                            ? `下载失败：${dlState.error || '未知错误'}，可重试或改用首次索引时自动下载。`
                            : '未下载：可在上方下载，或保存后首次索引时自动下载。'}
                      </p>
                    )}
                    {localEmbedError && (
                      <div className="rounded-lg bg-red-500/10 p-3 text-xs text-red-600">
                        <div className="font-medium">本地嵌入加载失败：{localEmbedError}</div>
                        {/torch|transformers/i.test(localEmbedError) && (
                          <div className="mt-1 text-red-600/90">
                            推理依赖缺失。请在项目 .venv 环境中执行：
                            <code className="rounded bg-black/10 px-1">python -m pip install torch transformers</code>
                            （Windows 默认即 CPU 版，约 2GB），安装后重建索引即可。
                          </div>
                        )}
                      </div>
                    )}
                  </div>
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
    </>
  )
}
