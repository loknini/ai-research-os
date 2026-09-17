import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import {
  CheckCircle2, Database, Download, ExternalLink, Eye, EyeOff, FileSearch,
  FunctionSquare, Key, Loader2, Save, TestTube, Upload, XCircle,
} from 'lucide-react'
import type { SettingsController } from '../hooks/useSettingsController'

interface PanelProps { settings: SettingsController }

export function IntegrationSettingsPanel({ settings }: PanelProps) {
  const { swanlabConfig, apiKey, setApiKey, apiUrl, setApiUrl, enabled, setEnabled, autoSync, setAutoSync, isLoading, isTesting, testResult, simpletexToken, setSimpletexToken, showToken, setShowToken, isSavingToken, setIsSavingToken, bochaApiKey, setBochaApiKey, showBochaKey, setShowBochaKey, bochaConfigured, bochaMasked, webSearchProvider, setWebSearchProvider, isSavingBocha, bochaStatus, fileInputRef, isExporting, isImporting, backupStatus, activeTab, handleSaveBocha, handleTestConnection, handleSaveConfig, handleExportBackup, handleImportFile } = settings
  return (
    <>
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
    </>
  )
}
