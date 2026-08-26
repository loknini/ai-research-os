import { useState, useRef, useCallback, useEffect } from 'react'
import { Header } from '@/components/layout/header'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useToast } from '@/components/ui/toast'
import { cn } from '@/utils'
import {
  Upload,
  Copy,
  Check,
  Star,
  Trash2,
  RefreshCw,
  Image as ImageIcon,
  FunctionSquare,
  History,
  Sparkles,
  Edit3,
  Save,
  X
} from 'lucide-react'

// 公式记录类型
interface FormulaRecord {
  id: string
  latex_code: string
  confidence: number
  source_type: string
  is_favorite: boolean
  tags: string[]
  note: string
  created_at: number
}

// 统计类型
interface FormulaStats {
  total: number
  favorites: number
  today: number
}

// LaTeX 预览组件
function LatexPreview({ latex, className }: { latex: string; className?: string }) {
  // 使用 MathJax 或 KaTeX 渲染
  // 这里简化显示，实际应该集成 MathJax
  return (
    <div className={cn("p-4 bg-muted/50 rounded-lg font-mono text-sm overflow-x-auto", className)}>
      <div className="text-muted-foreground mb-2 text-xs">预览:</div>
      <div className="text-lg">{latex}</div>
    </div>
  )
}

export default function FormulaHub({
  embedded = false,
  onInsert,
}: {
  embedded?: boolean
  /** 嵌入模式回填回调：识别成功后把 LaTeX 交回宿主（如插入笔记正文） */
  onInsert?: (latex: string) => void
} = {}) {
  const { showToast } = useToast()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const pasteAreaRef = useRef<HTMLDivElement>(null)
  
  // 检查是否配置了 API Token
  const [hasToken, setHasToken] = useState(false)
  
  useEffect(() => {
    const token = localStorage.getItem('simpletex_token')
    setHasToken(!!token)
  }, [])
  
  // 状态
  const [imageData, setImageData] = useState<string | null>(null)
  const [isRecognizing, setIsRecognizing] = useState(false)
  const [recognitionResult, setRecognitionResult] = useState<{
    latex: string
    confidence: number
    recordId?: string
  } | null>(null)
  const [useTurbo, setUseTurbo] = useState(false)
  
  // 历史记录
  const [history, setHistory] = useState<FormulaRecord[]>([])
  const [stats, setStats] = useState<FormulaStats>({ total: 0, favorites: 0, today: 0 })
  const [showFavoritesOnly, setShowFavoritesOnly] = useState(false)
  const [selectedRecord, setSelectedRecord] = useState<FormulaRecord | null>(null)
  const [editingNote, setEditingNote] = useState('')
  const [isEditing, setIsEditing] = useState(false)
  
  // 加载历史记录
  const loadHistory = useCallback(async () => {
    try {
      const response = await fetch(`/api/formula/history?favorites=${showFavoritesOnly}`)
      const result = await response.json()
      if (result.success) {
        setHistory(result.records ?? [])
      }
    } catch (error) {
      console.error('Failed to load history:', error)
    }
  }, [showFavoritesOnly])
  
  // 加载统计
  const loadStats = useCallback(async () => {
    try {
      const response = await fetch('/api/formula/stats')
      const result = await response.json()
      if (result.success) {
        setStats(result.stats ?? { total: 0, favorites: 0, today: 0 })
      }
    } catch (error) {
      console.error('Failed to load stats:', error)
    }
  }, [])
  
  useEffect(() => {
    loadHistory()
    loadStats()
  }, [loadHistory, loadStats])
  
  // 处理图片上传
  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    
    if (!file.type.startsWith('image/')) {
      showToast('请上传图片文件', 'error')
      return
    }
    
    const reader = new FileReader()
    reader.onload = (event) => {
      setImageData(event.target?.result as string)
      setRecognitionResult(null)
    }
    reader.readAsDataURL(file)
  }, [showToast])
  
  // 处理粘贴
  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData.items
    
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const blob = item.getAsFile()
        if (blob) {
          const reader = new FileReader()
          reader.onload = (event) => {
            setImageData(event.target?.result as string)
            setRecognitionResult(null)
            showToast('图片已粘贴', 'success')
          }
          reader.readAsDataURL(blob)
        }
        break
      }
    }
  }, [showToast])
  
  // 识别公式
  const recognizeFormula = useCallback(async () => {
    if (!imageData) {
      showToast('请先上传或粘贴图片', 'error')
      return
    }
    
    // 从 localStorage 读取 Token
    const token = localStorage.getItem('simpletex_token')
    if (!token) {
      showToast('请先配置 SimpleTex Token', 'error')
      return
    }
    
    setIsRecognizing(true)
    
    try {
      const response = await fetch('/api/formula/recognize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          imageBase64: imageData,
          useTurbo,
          token
        })
      })
      
      const result = await response.json()
      
      if (result.success) {
        setRecognitionResult({
          latex: result.latex,
          confidence: result.confidence,
          recordId: result.record_id
        })
        showToast('识别成功！', 'success')
        loadHistory()
        loadStats()
      } else {
        showToast(result.message || '识别失败', 'error')
      }
    } catch (error) {
      console.error('Recognition error:', error)
      showToast('识别请求失败', 'error')
    } finally {
      setIsRecognizing(false)
    }
  }, [imageData, useTurbo, showToast, loadHistory, loadStats])
  
  // 复制 LaTeX
  const copyLatex = useCallback(async (latex: string) => {
    try {
      await navigator.clipboard.writeText(latex)
      showToast('LaTeX 已复制', 'success')
    } catch {
      showToast('复制失败', 'error')
    }
  }, [showToast])
  
  // 切换收藏
  const toggleFavorite = useCallback(async (record: FormulaRecord) => {
    try {
      const response = await fetch('/api/formula/history', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: record.id,
          isFavorite: !record.is_favorite,
        })
      })
      
      const result = await response.json()
      if (result.success) {
        loadHistory()
        loadStats()
      }
    } catch (error) {
      console.error('Toggle favorite error:', error)
    }
  }, [loadHistory, loadStats])
  
  // 删除记录
  const deleteRecord = useCallback(async (id: string) => {
    try {
      const response = await fetch(`/api/formula/history/${id}`, {
        method: 'DELETE'
      })
      
      const result = await response.json()
      if (result.success) {
        showToast('记录已删除', 'success')
        loadHistory()
        loadStats()
        if (selectedRecord?.id === id) {
          setSelectedRecord(null)
        }
      }
    } catch (error) {
      console.error('Delete error:', error)
    }
  }, [loadHistory, loadStats, selectedRecord, showToast])
  
  // 保存笔记
  const saveNote = useCallback(async () => {
    if (!selectedRecord) return
    
    try {
      const response = await fetch('/api/formula/history', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: selectedRecord.id,
          note: editingNote,
        })
      })
      
      const result = await response.json()
      if (result.success) {
        showToast('笔记已保存', 'success')
        setIsEditing(false)
        loadHistory()
      }
    } catch (error) {
      console.error('Save note error:', error)
    }
  }, [selectedRecord, editingNote, loadHistory, showToast])
  
  return (
    <div className={embedded ? 'h-full flex flex-col overflow-hidden' : 'flex flex-col h-screen'}>
      {!embedded && (
        <Header
          title="公式识别"
          description="使用 SimpleTex AI 识别数学公式"
        />
      )}
      
      {/* API Key 未配置提示 */}
      {!hasToken && (
        <div className="mx-6 mt-4 p-4 bg-amber-500/10 border border-amber-500/20 rounded-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-amber-500/20 flex items-center justify-center">
                <svg className="w-4 h-4 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <div>
                <p className="font-medium text-amber-900 dark:text-amber-200">未配置 SimpleTex API Token</p>
                <p className="text-sm text-amber-700 dark:text-amber-300">公式识别功能需要配置 API Token 才能使用</p>
              </div>
            </div>
            <Button 
              variant="outline" 
              size="sm"
              className="border-amber-500/30 hover:bg-amber-500/10"
              onClick={() => window.location.href = '/settings'}
            >
              去设置
            </Button>
          </div>
        </div>
      )}
      
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧主区域 */}
        <div className="flex-1 p-6 overflow-auto">
          <div className="max-w-4xl mx-auto space-y-6">
            {/* 统计卡片 */}
            <div className="grid grid-cols-3 gap-4">
              <Card>
                <CardContent className="p-4 flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-blue-500/10 flex items-center justify-center">
                    <FunctionSquare className="w-5 h-5 text-blue-500" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">总识别数</p>
                    <p className="text-2xl font-bold">{stats.total}</p>
                  </div>
                </CardContent>
              </Card>
              
              <Card>
                <CardContent className="p-4 flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-yellow-500/10 flex items-center justify-center">
                    <Star className="w-5 h-5 text-yellow-500" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">收藏</p>
                    <p className="text-2xl font-bold">{stats.favorites}</p>
                  </div>
                </CardContent>
              </Card>
              
              <Card>
                <CardContent className="p-4 flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-green-500/10 flex items-center justify-center">
                    <Sparkles className="w-5 h-5 text-green-500" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">今日</p>
                    <p className="text-2xl font-bold">{stats.today}</p>
                  </div>
                </CardContent>
              </Card>
            </div>
            
            {/* 上传区域 */}
            <Card
              ref={pasteAreaRef}
              onPaste={handlePaste}
              className="border-2 border-dashed border-muted-foreground/25 hover:border-muted-foreground/50 transition-colors"
            >
              <CardContent className="p-8">
                {!imageData ? (
                  <div className="text-center space-y-4">
                    <div className="w-16 h-16 mx-auto rounded-full bg-muted flex items-center justify-center">
                      <ImageIcon className="w-8 h-8 text-muted-foreground" />
                    </div>
                    <div>
                      <p className="text-lg font-medium">上传或粘贴公式图片</p>
                      <p className="text-sm text-muted-foreground mt-1">
                        支持拖拽、点击上传或 Ctrl+V 粘贴
                      </p>
                    </div>
                    <div className="flex gap-2 justify-center">
                      <Button
                        variant="outline"
                        onClick={() => fileInputRef.current?.click()}
                      >
                        <Upload className="w-4 h-4 mr-2" />
                        选择图片
                      </Button>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/*"
                        onChange={handleFileUpload}
                        className="hidden"
                      />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="relative">
                      <img
                        src={imageData}
                        alt="Formula"
                        className="max-h-64 mx-auto rounded-lg border"
                      />
                      <Button
                        variant="ghost"
                        size="sm"
                        className="absolute top-2 right-2"
                        onClick={() => {
                          setImageData(null)
                          setRecognitionResult(null)
                        }}
                      >
                        <X className="w-4 h-4" />
                      </Button>
                    </div>
                    
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <label className="flex items-center gap-2 text-sm cursor-pointer">
                          <input
                            type="checkbox"
                            checked={useTurbo}
                            onChange={(e) => setUseTurbo(e.target.checked)}
                            className="rounded"
                          />
                          <span>使用轻量模型（更快）</span>
                        </label>
                      </div>
                      <Button
                        onClick={recognizeFormula}
                        disabled={isRecognizing}
                      >
                        {isRecognizing ? (
                          <>
                            <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                            识别中...
                          </>
                        ) : (
                          <>
                            <Sparkles className="w-4 h-4 mr-2" />
                            开始识别
                          </>
                        )}
                      </Button>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
            
            {/* 识别结果 */}
            {recognitionResult && (
              <Card className="border-green-500/20">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Check className="w-5 h-5 text-green-500" />
                    识别结果
                    <Badge variant="secondary">
                      置信度: {(recognitionResult.confidence * 100).toFixed(1)}%
                    </Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="relative">
                    <pre className="p-4 bg-muted rounded-lg font-mono text-sm overflow-x-auto">
                      {recognitionResult.latex}
                    </pre>
                    <div className="absolute top-2 right-2 flex gap-1">
                      {onInsert && (
                        <Button
                          size="sm"
                          className="h-8"
                          onClick={() => onInsert(recognitionResult.latex)}
                        >
                          <Save className="w-3.5 h-3.5 mr-1" />
                          插入到笔记
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8"
                        onClick={() => copyLatex(recognitionResult.latex)}
                      >
                        <Copy className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                  
                  <LatexPreview latex={recognitionResult.latex} />
                </CardContent>
              </Card>
            )}
            
            {/* 选中历史记录的详情 */}
            {selectedRecord && (
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="flex items-center gap-2">
                      <History className="w-5 h-5" />
                      历史记录详情
                    </CardTitle>
                    <div className="flex gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => toggleFavorite(selectedRecord)}
                      >
                        <Star
                          className={cn(
                            "w-4 h-4",
                            selectedRecord.is_favorite && "fill-yellow-500 text-yellow-500"
                          )}
                        />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => deleteRecord(selectedRecord.id)}
                      >
                        <Trash2 className="w-4 h-4 text-red-500" />
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="relative">
                    <pre className="p-4 bg-muted rounded-lg font-mono text-sm overflow-x-auto">
                      {selectedRecord.latex_code}
                    </pre>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="absolute top-2 right-2"
                      onClick={() => copyLatex(selectedRecord.latex_code)}
                    >
                      <Copy className="w-4 h-4" />
                    </Button>
                  </div>
                  
                  <LatexPreview latex={selectedRecord.latex_code} />
                  
                  {/* 笔记 */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">笔记</span>
                      {!isEditing ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setEditingNote(selectedRecord.note || '')
                            setIsEditing(true)
                          }}
                        >
                          <Edit3 className="w-4 h-4 mr-1" />
                          编辑
                        </Button>
                      ) : (
                        <div className="flex gap-2">
                          <Button variant="ghost" size="sm" onClick={saveNote}>
                            <Save className="w-4 h-4 mr-1" />
                            保存
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setIsEditing(false)}
                          >
                            <X className="w-4 h-4" />
                          </Button>
                        </div>
                      )}
                    </div>
                    {isEditing ? (
                      <textarea
                        value={editingNote}
                        onChange={(e) => setEditingNote(e.target.value)}
                        className="w-full h-24 p-3 rounded-md border border-input bg-background resize-none"
                        placeholder="添加笔记..."
                      />
                    ) : (
                      <p className="text-sm text-muted-foreground p-3 bg-muted rounded-lg">
                        {selectedRecord.note || '暂无笔记'}
                      </p>
                    )}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
        
        {/* 右侧历史记录 */}
        <div className="w-80 border-l bg-muted/30">
          <div className="p-4 border-b bg-card">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold flex items-center gap-2">
                <History className="w-4 h-4" />
                识别历史
              </h3>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowFavoritesOnly(!showFavoritesOnly)}
              >
                <Star
                  className={cn(
                    "w-4 h-4",
                    showFavoritesOnly && "fill-yellow-500 text-yellow-500"
                  )}
                />
              </Button>
            </div>
          </div>
          
          <ScrollArea className="h-[calc(100vh-180px)]">
            <div className="p-2 space-y-1">
              {history.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <p className="text-sm">暂无记录</p>
                </div>
              ) : (
                history.map((record) => (
                  <button
                    key={record.id}
                    onClick={() => {
                      setSelectedRecord(record)
                      setEditingNote(record.note || '')
                      setIsEditing(false)
                    }}
                    className={cn(
                      "w-full p-3 text-left rounded-lg transition-colors",
                      selectedRecord?.id === record.id
                        ? "bg-primary/10 border border-primary/20"
                        : "hover:bg-muted"
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <code className="text-xs font-mono truncate flex-1">
                        {record.latex_code.slice(0, 30)}...
                      </code>
                      {record.is_favorite && (
                        <Star className="w-3 h-3 text-yellow-500 fill-yellow-500 flex-shrink-0" />
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                      <Badge variant="secondary" className="text-xs">
                        {(record.confidence * 100).toFixed(0)}%
                      </Badge>
                      <span>
                        {new Date(record.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </button>
                ))
              )}
            </div>
          </ScrollArea>
        </div>
      </div>
    </div>
  )
}
