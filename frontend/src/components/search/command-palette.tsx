import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/utils'
import { commandGroups, type NavItem } from '@/config/navigation'
import {
  FileText,
  CheckSquare,
  Code2,
  BookOpen,
  FlaskConical,
  Search,
  Loader2,
  Command,
  ArrowRight,
  CornerDownLeft,
  LayoutGrid,
  Settings,
} from 'lucide-react'

// 命令条目（来自导航 manifest，供键盘导航与渲染统一消费）
interface CommandEntry extends NavItem {
  kind: 'command'
  groupLabel: string
}

// 搜索结果类型
interface SearchResult {
  kind: 'search'
  id: string
  title: string
  description: string
  type: 'paper' | 'task' | 'project' | 'note' | 'experiment'
  path: string
  icon: React.ElementType
  color: string
  bgColor: string
  label: string
}

// 类型配置
const typeConfig = {
  paper: {
    icon: FileText,
    color: 'text-blue-500',
    bgColor: 'bg-blue-500/10',
    label: '论文',
    pathPrefix: '/paper',
  },
  task: {
    icon: CheckSquare,
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
    label: '任务',
    pathPrefix: '/task',
  },
  project: {
    icon: Code2,
    color: 'text-purple-500',
    bgColor: 'bg-purple-500/10',
    label: '项目',
    pathPrefix: '/software',
  },
  note: {
    icon: BookOpen,
    color: 'text-orange-500',
    bgColor: 'bg-orange-500/10',
    label: '笔记',
    pathPrefix: '/knowledge',
  },
  experiment: {
    icon: FlaskConical,
    color: 'text-cyan-500',
    bgColor: 'bg-cyan-500/10',
    label: '实验',
    pathPrefix: '/experiment',
  },
}

// 组标签 → 图标（命令面板分组头）
const groupIconMap: Record<string, React.ElementType> = {
  research: LayoutGrid,
  dev: Code2,
  system: Settings,
}

// 把 manifest 命令包装为命令条目（带分组标签）
function buildCommandEntries(items: NavItem[], groupLabel: string): CommandEntry[] {
  return items.map((item) => ({ ...item, kind: 'command', groupLabel }))
}

// 全量命令条目（无查询时展示，顺序 = 分组顺序，保证键盘索引一致）
const ALL_COMMAND_ENTRIES: CommandEntry[] = commandGroups.flatMap((group) =>
  buildCommandEntries(group.items, group.label)
)

interface CommandPaletteProps {
  isGlobal?: boolean
}

export function CommandPalette({ isGlobal = true }: CommandPaletteProps) {
  const navigate = useNavigate()
  const [isOpen, setIsOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  // 监听快捷键（仅在全局模式下）
  useEffect(() => {
    if (!isGlobal) return

    const handleKeyDown = (e: KeyboardEvent) => {
      // Command/Ctrl + K
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setIsOpen(true)
      }
      // Escape 关闭
      if (e.key === 'Escape' && isOpen) {
        setIsOpen(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, isGlobal])

  // 自动聚焦输入框 + 打开时锁定背景滚动
  useEffect(() => {
    if (isOpen && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 100)
    }
    if (isOpen) {
      const originalOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
      return () => {
        document.body.style.overflow = originalOverflow
      }
    }
  }, [isOpen])

  // 过滤命令（按名称 / 描述 / 关键词 / id）
  const filteredCommands = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return ALL_COMMAND_ENTRIES
    return ALL_COMMAND_ENTRIES.filter(
      (cmd) =>
        cmd.name.toLowerCase().includes(q) ||
        cmd.description.toLowerCase().includes(q) ||
        cmd.id.toLowerCase().includes(q) ||
        (cmd.keywords || []).some((kw) => kw.toLowerCase().includes(q))
    )
  }, [query])

  // 搜索
  const search = useCallback(async (searchQuery: string) => {
    if (!searchQuery.trim()) {
      setResults([])
      return
    }

    setIsSearching(true)
    try {
      const response = await fetch(`/api/search?q=${encodeURIComponent(searchQuery)}&limit=20`)
      const data = await response.json()

      if (data.success) {
        const formattedResults: SearchResult[] = []

        // 格式化论文
        data.results.papers?.forEach((paper: any) => {
          formattedResults.push({
            kind: 'search',
            id: paper.id,
            title: paper.title,
            description: paper.authors?.slice(0, 3).join(', ') || '',
            type: 'paper',
            path: '/paper',
            icon: typeConfig.paper.icon,
            color: typeConfig.paper.color,
            bgColor: typeConfig.paper.bgColor,
            label: typeConfig.paper.label,
          })
        })

        // 格式化任务
        data.results.tasks?.forEach((task: any) => {
          formattedResults.push({
            kind: 'search',
            id: task.id,
            title: task.title,
            description: task.description || '',
            type: 'task',
            path: '/task',
            icon: typeConfig.task.icon,
            color: typeConfig.task.color,
            bgColor: typeConfig.task.bgColor,
            label: typeConfig.task.label,
          })
        })

        // 格式化项目
        data.results.projects?.forEach((project: any) => {
          formattedResults.push({
            kind: 'search',
            id: project.id,
            title: project.name,
            description: project.description || '',
            type: 'project',
            path: '/software',
            icon: typeConfig.project.icon,
            color: typeConfig.project.color,
            bgColor: typeConfig.project.bgColor,
            label: typeConfig.project.label,
          })
        })

        // 格式化笔记
        data.results.notes?.forEach((note: any) => {
          formattedResults.push({
            kind: 'search',
            id: note.id,
            title: note.title,
            description: note.content?.slice(0, 100) + '...' || '',
            type: 'note',
            path: '/knowledge',
            icon: typeConfig.note.icon,
            color: typeConfig.note.color,
            bgColor: typeConfig.note.bgColor,
            label: typeConfig.note.label,
          })
        })

        // 格式化实验
        data.results.experiments?.forEach((exp: any) => {
          formattedResults.push({
            kind: 'search',
            id: exp.id,
            title: exp.name,
            description: exp.description || '',
            type: 'experiment',
            path: '/experiment',
            icon: typeConfig.experiment.icon,
            color: typeConfig.experiment.color,
            bgColor: typeConfig.experiment.bgColor,
            label: typeConfig.experiment.label,
          })
        })

        setResults(formattedResults)
        setSelectedIndex(0)
      }
    } catch (error) {
      console.error('Search error:', error)
    } finally {
      setIsSearching(false)
    }
  }, [])

  // 防抖搜索
  useEffect(() => {
    const timer = setTimeout(() => {
      search(query)
    }, 300)
    return () => clearTimeout(timer)
  }, [query, search])

  // 统一导航条目：命令在前，搜索结果在后（顺序与渲染一致）
  const navItems = useMemo(() => {
    const cmds = filteredCommands
    const res = query.trim() ? results : []
    const items: (CommandEntry | SearchResult)[] = [...cmds, ...res]
    // 索引越界保护
    setSelectedIndex((prev) => Math.min(prev, Math.max(0, items.length - 1)))
    return items
  }, [filteredCommands, results, query])

  // 键盘导航
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (navItems.length === 0) return

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault()
          setSelectedIndex((prev) => (prev + 1) % navItems.length)
          break
        case 'ArrowUp':
          e.preventDefault()
          setSelectedIndex((prev) => (prev - 1 + navItems.length) % navItems.length)
          break
        case 'Enter':
          e.preventDefault()
          const selected = navItems[selectedIndex]
          if (selected) {
            navigate(selected.path)
            setIsOpen(false)
            setQuery('')
          }
          break
      }
    },
    [navItems, selectedIndex, navigate]
  )

  // 选择结果
  const selectItem = (item: CommandEntry | SearchResult) => {
    navigate(item.path)
    setIsOpen(false)
    setQuery('')
  }

  // 获取快捷键提示
  const getShortcutText = () => {
    if (navigator.platform.toLowerCase().includes('mac')) {
      return '⌘K'
    }
    return 'Ctrl+K'
  }

  // 渲染单个命令条目
  const renderCommandItem = (cmd: CommandEntry, index: number) => {
    const Icon = cmd.icon
    return (
      <button
        key={`cmd-${cmd.id}`}
        onClick={() => selectItem(cmd)}
        onMouseEnter={() => setSelectedIndex(index)}
        className={cn(
          'w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors',
          index === selectedIndex && 'bg-accent'
        )}
      >
        <div className="w-8 h-8 rounded-lg bg-foreground/[0.06] flex items-center justify-center flex-shrink-0">
          <Icon className="w-4 h-4 text-muted-foreground" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="font-medium truncate">{cmd.name}</p>
            {query.trim() && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-foreground/[0.06] text-muted-foreground">
                {cmd.groupLabel}
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground truncate">{cmd.description}</p>
        </div>
        {index === selectedIndex && <ArrowRight className="w-4 h-4 text-muted-foreground" />}
      </button>
    )
  }

  // 渲染单个搜索结果
  const renderSearchItem = (result: SearchResult, index: number) => {
    const Icon = result.icon
    const config = typeConfig[result.type]
    return (
      <button
        key={`${result.type}-${result.id}`}
        onClick={() => selectItem(result)}
        onMouseEnter={() => setSelectedIndex(index)}
        className={cn(
          'w-full flex items-start gap-3 px-4 py-3 text-left transition-colors',
          index === selectedIndex && 'bg-accent'
        )}
      >
        <div
          className={cn(
            'w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0',
            config.bgColor
          )}
        >
          <Icon className={cn('w-4 h-4', result.color)} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="font-medium truncate">{result.title}</p>
            <span
              className={cn(
                'text-xs px-1.5 py-0.5 rounded',
                config.bgColor,
                config.color
              )}
            >
              {result.label}
            </span>
          </div>
          <p className="text-sm text-muted-foreground truncate">{result.description}</p>
        </div>
        {index === selectedIndex && <ArrowRight className="w-4 h-4 text-muted-foreground" />}
      </button>
    )
  }

  // 无查询时：命令按分组展示（分组标题不参与键盘索引，条目顺序与 navItems 一致）
  const renderGroupedCommands = () => {
    let offset = 0
    return (
      <div className="py-2">
        {commandGroups.map((group) => {
          const GroupIcon = groupIconMap[group.id] || LayoutGrid
          const groupItems = buildCommandEntries(group.items, group.label)
          const start = offset
          offset += groupItems.length
          if (groupItems.length === 0) return null
          return (
            <div key={group.id}>
              <p className="flex items-center gap-1.5 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                <GroupIcon className="w-3 h-3" />
                {group.label}
              </p>
              {groupItems.map((cmd, i) => renderCommandItem(cmd, start + i))}
            </div>
          )
        })}
      </div>
    )
  }

  const hasQuery = query.trim().length > 0
  const totalCount = navItems.length

  return (
    <>
      {/* 触发按钮（仅在非全局模式下显示） */}
      {!isGlobal && (
        <button
          onClick={() => setIsOpen(true)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted hover:bg-accent transition-colors text-sm text-muted-foreground"
        >
          <Search className="w-4 h-4" />
          <span>搜索...</span>
          <kbd className="ml-2 px-1.5 py-0.5 rounded bg-background text-xs border">
            {getShortcutText()}
          </kbd>
        </button>
      )}

      {/* 搜索面板（Portal 到 body，避免被 glass 面板覆盖） */}
      {isOpen &&
        createPortal(
          <div
            className="fixed inset-0 z-[100] bg-black/40 backdrop-blur-sm flex items-start justify-center pt-[10vh]"
            onClick={() => setIsOpen(false)}
            aria-modal="true"
            role="dialog"
            aria-label="全局搜索与命令"
          >
            <div
              className="w-[calc(100%-2rem)] max-w-2xl glass rounded-2xl shadow-2xl border border-border/50 overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
            {/* 搜索输入 */}
            <div className="flex items-center gap-3 px-4 py-3 border-b">
              <Search className="w-5 h-5 text-muted-foreground" />
              <Input
                ref={inputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="搜索数据或输入命令名（公式、引用、任务...）"
                className="flex-1 border-0 focus-visible:ring-0 focus-visible:ring-offset-0 text-lg"
              />
              {isSearching && <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />}
              <button
                onClick={() => setIsOpen(false)}
                className="p-1 hover:bg-muted rounded"
              >
                <kbd className="px-2 py-1 rounded bg-muted text-xs">ESC</kbd>
              </button>
            </div>

            {/* 内容区 */}
            <ScrollArea className="max-h-[400px]">
              {!hasQuery && (
                <>
                  {/* 命令分组（无查询默认展示） */}
                  {renderGroupedCommands()}
                  {/* 底部快捷提示 */}
                  <div className="px-4 py-3 border-t border-border/40 bg-foreground/[0.03] text-xs text-muted-foreground">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-4">
                        <span className="flex items-center gap-1">
                          <CornerDownLeft className="w-3 h-3" /> 打开
                        </span>
                        <span className="flex items-center gap-1">
                          <span className="font-mono">↑↓</span> 导航
                        </span>
                        <span className="flex items-center gap-1">
                          <Command className="w-3 h-3" /> 输入关键词搜索数据
                        </span>
                      </div>
                      <span>{totalCount} 个命令</span>
                    </div>
                  </div>
                </>
              )}

              {hasQuery && (
                <>
                  {navItems.length === 0 && !isSearching && (
                    <div className="p-8 text-center text-muted-foreground">
                      <Search className="w-12 h-12 mx-auto mb-4 opacity-50" />
                      <p>没有找到相关结果</p>
                    </div>
                  )}

                  <div className="py-2">
                    {filteredCommands.length > 0 && (
                      <>
                        <p className="px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/60 flex items-center gap-1.5">
                          <Command className="w-3 h-3" />
                          命令 · {filteredCommands.length}
                        </p>
                        {filteredCommands.map((cmd, i) => renderCommandItem(cmd, i))}
                      </>
                    )}

                    {results.length > 0 && (
                      <>
                        <p className="px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/60 flex items-center gap-1.5">
                          <Search className="w-3 h-3" />
                          搜索结果 · {results.length}
                        </p>
                        {results.map((result, i) => renderSearchItem(result, filteredCommands.length + i))}
                      </>
                    )}
                  </div>

                  {totalCount > 0 && (
                    <div className="flex items-center justify-between px-4 py-2 border-t border-border/40 bg-foreground/[0.03] text-xs text-muted-foreground">
                      <div className="flex items-center gap-4">
                        <span className="flex items-center gap-1">
                          <CornerDownLeft className="w-3 h-3" /> 打开
                        </span>
                        <span className="flex items-center gap-1">
                          <span className="font-mono">↑↓</span> 导航
                        </span>
                      </div>
                      <span>{totalCount} 个结果</span>
                    </div>
                  )}
                </>
              )}
            </ScrollArea>
          </div>
        </div>,
        document.body
      )}
    </>
  )
}

// 使用全局搜索的 Hook
export function useCommandPalette() {
  const [isOpen, setIsOpen] = useState(false)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setIsOpen(true)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  return { isOpen, setIsOpen }
}
