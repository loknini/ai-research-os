import { useState, useCallback, useEffect, useRef } from 'react'
import { Header } from '@/components/layout/header'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useToast } from '@/components/ui/toast'
import { cn } from '@/utils'
import {
  Search,
  Copy,
  Check,
  Quote,
  BookType,
  Library,
  Loader2,
  History,
  Trash2,
  Save
} from 'lucide-react'

// 论文类型
interface Paper {
  doi: string
  title: string
  authors: { given: string; family: string; full: string }[]
  year: number | null
  journal: string
  journal_short: string
  volume: string
  issue: string
  page: string
  publisher: string
  type: string
  url: string
}

// 引用历史类型
interface CitationHistory {
  id: string
  query: string
  paper: Paper
  formats: Record<string, string>
  created_at: number
}

// 支持的引用格式
const CITATION_FORMATS = [
  { id: 'apa', name: 'APA 7th', description: '美国心理学会格式' },
  { id: 'mla', name: 'MLA 9th', description: '现代语言协会格式' },
  { id: 'chicago', name: 'Chicago 17th', description: '芝加哥格式' },
  { id: 'gb7714', name: 'GB/T 7714', description: '中国国家标准' },
  { id: 'bibtex', name: 'BibTeX', description: 'LaTeX 引用格式' },
  { id: 'ris', name: 'RIS', description: '文献管理软件格式' },
]

// 格式化作者显示
function formatAuthors(authors: Paper['authors'], maxCount: number = 3): string {
  if (!authors || authors.length === 0) return 'Unknown'
  
  if (authors.length <= maxCount) {
    return authors.map(a => a.family).join(', ')
  }
  
  return `${authors.slice(0, maxCount).map(a => a.family).join(', ')} et al.`
}

interface CitationHubProps {
  embedded?: boolean
  /** 嵌入模式预填查询（如论文标题），首次挂载自动搜索 */
  initialQuery?: string
  /** 嵌入模式回填回调：格式 id + 引用文本（如 ('bibtex', '@article{...}')） */
  onInsert?: (format: string, text: string) => void
}

export default function CitationHub({
  embedded = false,
  initialQuery,
  onInsert,
}: CitationHubProps = {}) {
  const { showToast } = useToast()
  const autoSearchRef = useRef(false)
  const searchPapersRef = useRef<(() => void) | null>(null)

  // 搜索状态
  const [query, setQuery] = useState(initialQuery || '')
  const [isSearching, setIsSearching] = useState(false)
  const [searchResults, setSearchResults] = useState<Paper[]>([])
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null)
  
  // 引用生成状态
  const [citations, setCitations] = useState<Record<string, string>>({})
  const [isGenerating, setIsGenerating] = useState(false)
  const [copiedFormat, setCopiedFormat] = useState<string | null>(null)
  
  // 历史记录
  const [history, setHistory] = useState<CitationHistory[]>([])
  const [showHistory, setShowHistory] = useState(false)
  
  // 当前选中的引用格式
  const [activeFormat, setActiveFormat] = useState(embedded && onInsert ? 'bibtex' : 'apa')

  // 嵌入模式：initialQuery 预填并自动搜索一次
  useEffect(() => {
    if (!initialQuery || autoSearchRef.current) return
    autoSearchRef.current = true
    setQuery(initialQuery)
    const timer = setTimeout(() => {
      searchPapersRef.current?.()
    }, 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery])
  
  // 从 localStorage 加载历史
  useEffect(() => {
    const saved = localStorage.getItem('citation_history')
    if (saved) {
      try {
        setHistory(JSON.parse(saved))
      } catch {
        // 解析失败，忽略
      }
    }
  }, [])
  
  // 保存历史到 localStorage
  const saveHistory = useCallback((newHistory: CitationHistory[]) => {
    localStorage.setItem('citation_history', JSON.stringify(newHistory.slice(0, 50)))
    setHistory(newHistory)
  }, [])
  
  // 搜索论文
  const searchPapers = useCallback(async () => {
    if (!query.trim()) {
      showToast('请输入论文标题、DOI 或关键词', 'error')
      return
    }
    
    setIsSearching(true)
    setSearchResults([])
    setSelectedPaper(null)
    setCitations({})
    
    try {
      // 调用后端 API
      const response = await fetch(`/api/citation/search?q=${encodeURIComponent(query)}`)
      const result = await response.json()
      
      if (result.success) {
        setSearchResults(result.papers || [])
        if (result.papers?.length === 0) {
          showToast('未找到相关论文', 'info')
        }
      } else {
        showToast(result.message || '搜索失败', 'error')
      }
    } catch (error) {
      console.error('Search error:', error)
      showToast('搜索请求失败', 'error')
    } finally {
      setIsSearching(false)
    }
  }, [query, showToast])
  // 供嵌入模式自动搜索引用（避免依赖顺序问题）
  searchPapersRef.current = searchPapers

  // 生成引用
  const generateCitations = useCallback(async (paper: Paper) => {
    setIsGenerating(true)
    setSelectedPaper(paper)
    
    try {
      const response = await fetch('/api/citation/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paper })
      })
      
      const result = await response.json()
      
      if (result.success) {
        setCitations(result.citations || {})
        
        // 添加到历史
        const newEntry: CitationHistory = {
          id: Date.now().toString(),
          query,
          paper,
          formats: result.citations || {},
          created_at: Date.now()
        }
        saveHistory([newEntry, ...history])
      } else {
        showToast(result.message || '生成失败', 'error')
      }
    } catch (error) {
      console.error('Generate error:', error)
      showToast('生成请求失败', 'error')
    } finally {
      setIsGenerating(false)
    }
  }, [query, history, saveHistory, showToast])
  
  // 复制引用
  const copyCitation = useCallback(async (format: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedFormat(format)
      showToast(`${format.toUpperCase()} 格式已复制`, 'success')
      setTimeout(() => setCopiedFormat(null), 2000)
    } catch {
      showToast('复制失败', 'error')
    }
  }, [showToast])
  
  // 删除历史记录
  const deleteHistoryItem = useCallback((id: string) => {
    const newHistory = history.filter(h => h.id !== id)
    saveHistory(newHistory)
    showToast('已删除', 'success')
  }, [history, saveHistory, showToast])
  
  // 从历史加载
  const loadFromHistory = useCallback((item: CitationHistory) => {
    setSelectedPaper(item.paper)
    setCitations(item.formats)
    setQuery(item.query)
    setShowHistory(false)
  }, [])
  
  return (
    <div className={embedded ? 'h-full flex flex-col overflow-hidden' : 'flex flex-col h-screen'}>
      {!embedded && (
        <Header
          title="参考文献引用"
          description="通过 Crossref 免费获取论文引用格式"
        />
      )}
      
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧主区域 */}
        <div className="flex-1 p-6 overflow-auto">
          <div className="max-w-5xl mx-auto space-y-6">
            {/* 搜索区域 */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Search className="w-5 h-5" />
                  搜索论文
                </CardTitle>
                <CardDescription>
                  输入论文标题、DOI 或关键词进行搜索
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex gap-2">
                  <Input
                    placeholder="例如：Attention Is All You Need 或 10.1145/276524.276685"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && searchPapers()}
                    className="flex-1"
                  />
                  <Button 
                    onClick={searchPapers}
                    disabled={isSearching || !query.trim()}
                  >
                    {isSearching ? (
                      <Loader2 className="w-4 h-4 animate-spin mr-2" />
                    ) : (
                      <Search className="w-4 h-4 mr-2" />
                    )}
                    搜索
                  </Button>
                </div>
                
                <div className="text-xs text-muted-foreground">
                  <p>支持的搜索方式：</p>
                  <ul className="list-disc list-inside mt-1 space-y-0.5">
                    <li>论文标题（如：Deep Residual Learning for Image Recognition）</li>
                    <li>DOI（如：10.1038/s41586-021-03819-2）</li>
                    <li>作者 + 关键词（如：Smith machine learning）</li>
                  </ul>
                </div>
              </CardContent>
            </Card>
            
            {/* 搜索结果 */}
            {searchResults.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Library className="w-5 h-5" />
                    搜索结果
                    <Badge variant="secondary">{searchResults.length}</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ScrollArea className="h-[300px]">
                    <div className="space-y-3">
                      {searchResults.map((paper, index) => (
                        <button
                          key={paper.doi || index}
                          onClick={() => generateCitations(paper)}
                          className={cn(
                            "w-full p-4 text-left rounded-lg border transition-all",
                            selectedPaper?.doi === paper.doi
                              ? "border-primary bg-primary/5"
                              : "border-border hover:border-primary/50 hover:bg-muted/50"
                          )}
                        >
                          <h4 className="font-medium line-clamp-2 mb-2">{paper.title}</h4>
                          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
                            <span>{formatAuthors(paper.authors)}</span>
                            {paper.year && <span>· {paper.year}</span>}
                            {paper.journal && <span>· {paper.journal}</span>}
                          </div>
                          {paper.doi && (
                            <div className="mt-2 text-xs text-muted-foreground">
                              DOI: {paper.doi}
                            </div>
                          )}
                        </button>
                      ))}
                    </div>
                  </ScrollArea>
                </CardContent>
              </Card>
            )}
            
            {/* 引用格式展示 */}
            {selectedPaper && (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Quote className="w-5 h-5" />
                    引用格式
                    {isGenerating && <Loader2 className="w-4 h-4 animate-spin" />}
                  </CardTitle>
                  <CardDescription>
                    {selectedPaper.title}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {Object.keys(citations).length > 0 ? (
                    <div className="w-full">
                      {/* 格式选择按钮 */}
                      <div className="grid grid-cols-6 gap-1 p-1 bg-muted rounded-lg">
                        {CITATION_FORMATS.map(fmt => (
                          <button
                            key={fmt.id}
                            onClick={() => setActiveFormat(fmt.id)}
                            className={cn(
                              "px-3 py-2 text-sm font-medium rounded-md transition-all",
                              activeFormat === fmt.id
                                ? "bg-background text-foreground shadow-sm"
                                : "text-muted-foreground hover:text-foreground"
                            )}
                          >
                            {fmt.name.split(' ')[0]}
                          </button>
                        ))}
                      </div>
                      
                      {/* 当前格式的引用内容 */}
                      <div className="mt-4">
                        {CITATION_FORMATS.map(fmt => (
                          activeFormat === fmt.id && (
                            <div key={fmt.id}>
                              <div className="relative">
                                <pre className="p-4 bg-muted rounded-lg text-sm whitespace-pre-wrap font-mono overflow-x-auto">
                                  {citations[fmt.id] || '生成中...'}
                                </pre>
                                <div className="absolute top-2 right-2 flex gap-1">
                                  {onInsert && fmt.id === 'bibtex' && citations.bibtex && (
                                    <Button
                                      size="sm"
                                      className="h-8"
                                      onClick={() => onInsert('bibtex', citations.bibtex)}
                                    >
                                      <Save className="w-3.5 h-3.5 mr-1" />
                                      保存到论文
                                    </Button>
                                  )}
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-8"
                                    onClick={() => copyCitation(fmt.id, citations[fmt.id])}
                                    disabled={!citations[fmt.id]}
                                  >
                                    {copiedFormat === fmt.id ? (
                                      <Check className="w-4 h-4 text-green-500" />
                                    ) : (
                                      <Copy className="w-4 h-4" />
                                    )}
                                  </Button>
                                </div>
                              </div>
                              <p className="mt-2 text-xs text-muted-foreground">
                                {fmt.description}
                              </p>
                            </div>
                          )
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center justify-center py-12 text-muted-foreground">
                      <Loader2 className="w-5 h-5 animate-spin mr-2" />
                      正在生成引用格式...
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
            
            {/* 使用说明 */}
            <Card className="bg-muted/50">
              <CardHeader>
                <CardTitle className="text-base">支持的引用格式</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
                  {CITATION_FORMATS.map(fmt => (
                    <div key={fmt.id} className="flex items-start gap-2">
                      <BookType className="w-4 h-4 mt-0.5 text-muted-foreground" />
                      <div>
                        <p className="font-medium">{fmt.name}</p>
                        <p className="text-xs text-muted-foreground">{fmt.description}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
        
        {/* 右侧历史记录 */}
        <div className={cn(
          "border-l bg-muted/30 transition-all duration-300",
          showHistory ? "w-80" : "w-12"
        )}>
          <div className="p-2">
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-center"
              onClick={() => setShowHistory(!showHistory)}
            >
              <History className="w-4 h-4" />
              {showHistory && <span className="ml-2">历史记录</span>}
            </Button>
          </div>
          
          {showHistory && (
            <ScrollArea className="h-[calc(100vh-140px)]">
              <div className="p-2 space-y-2">
                {history.length === 0 ? (
                  <div className="text-center py-8 text-muted-foreground text-sm">
                    <p>暂无历史记录</p>
                  </div>
                ) : (
                  history.map((item) => (
                    <Card key={item.id} className="cursor-pointer hover:border-primary/50">
                      <CardContent className="p-3">
                        <div 
                          onClick={() => loadFromHistory(item)}
                          className="space-y-2"
                        >
                          <p className="text-sm font-medium line-clamp-2">
                            {item.paper.title}
                          </p>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <span>{item.paper.year || 'Unknown'}</span>
                            <span>·</span>
                            <span>{formatAuthors(item.paper.authors, 1)}</span>
                          </div>
                        </div>
                        <div className="flex items-center justify-between mt-2 pt-2 border-t">
                          <span className="text-xs text-muted-foreground">
                            {new Date(item.created_at).toLocaleDateString()}
                          </span>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 p-0"
                            onClick={(e) => {
                              e.stopPropagation()
                              deleteHistoryItem(item.id)
                            }}
                          >
                            <Trash2 className="w-3 h-3 text-red-500" />
                          </Button>
                        </div>
                      </CardContent>
                    </Card>
                  ))
                )}
              </div>
            </ScrollArea>
          )}
        </div>
      </div>
    </div>
  )
}
