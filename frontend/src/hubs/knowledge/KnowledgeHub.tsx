// Knowledge Hub container.
// Extracted from the original monolithic index.tsx (909 lines). This file keeps the
// component state, the handlers (now delegating fetch logic to ./services/*), and the
// JSX assembly of the presentational components. External behavior, props and render
// output are identical to the source.

import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { Header, HeaderAction } from '@/components/layout/header'
import { cn } from '@/utils'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { toast } from '@/components/ui/toast'
import type { Note } from '@/types'
import {
  Plus,
  Search,
  BookOpen,
  Lightbulb,
  FileText,
  Star,
  Filter,
  FolderOpen,
  RefreshCw,
  Link2,
  FunctionSquare,
  BrainCircuit,
  History,
  X
} from 'lucide-react'
import { NOTE_TYPE_CONFIG } from './config'
import type { ObsidianVault, ObsidianFile, ObsidianFileDetail } from './types'
import { fetchNotes, saveNote, updateNote, deleteNoteApi } from './services/notesApi'
import { fetchVaults, fetchVaultFiles, fetchObsidianFile, scanVault, addVault } from './services/obsidianApi'
import { useKnowledgeData } from './hooks/useKnowledgeData'
import { NoteCard } from './components/NoteCard'
import { NoteEditor } from './components/NoteEditor'
import { VaultSelectorDialog } from './components/VaultSelectorDialog'
import { ObsidianFileViewer } from './components/ObsidianFileViewer'
import { ObsidianFileBrowser } from './components/ObsidianFileBrowser'
import FormulaHub from '@/hubs/formula'
import { TeamContextRunDialog } from '@/components/agent/team-context-run-dialog'
import { useSearchParams } from 'react-router-dom'

export default function KnowledgeHub() {
  const [searchParams, setSearchParams] = useSearchParams()
  // 状态
  const [notes, setNotes] = useState<Note[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [showEditor, setShowEditor] = useState(false)
  const [editingNote, setEditingNote] = useState<Note | null>(null)
  const [deletingNote, setDeletingNote] = useState<Note | null>(null)
  const [selectedNote, setSelectedNote] = useState<Note | null>(null)

  // Obsidian Vault 状态
  const [obsidianVaults, setObsidianVaults] = useState<ObsidianVault[]>([])
  const [obsidianFiles, setObsidianFiles] = useState<ObsidianFile[]>([])
  const [selectedVault, setSelectedVault] = useState<number | null>(null)
  const selectedVaultRef = useRef<number | null>(null)
  selectedVaultRef.current = selectedVault
  const [selectedObsidianFile, setSelectedObsidianFile] = useState<ObsidianFile | null>(null)
  const [obsidianFileDetail, setObsidianFileDetail] = useState<ObsidianFileDetail | null>(null)
  const [isObsidianFileLoading, setIsObsidianFileLoading] = useState(false)
  const [obsidianFileError, setObsidianFileError] = useState<string | null>(null)
  const obsidianFileRequestRef = useRef(0)
  const [isScanning, setIsScanning] = useState(false)
  const [showVaultSelector, setShowVaultSelector] = useState(false)
  const [vaultPathInput, setVaultPathInput] = useState('')
  const [vaultNameInput, setVaultNameInput] = useState('')
  const [obsidianViewMode, setObsidianViewMode] = useState<'tree' | 'recent'>('tree')

  // 筛选状态
  const [filterType, setFilterType] = useState<string>('all')
  const [filterFavorite, setFilterFavorite] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [activeTab, setActiveTab] = useState<'local' | 'obsidian' | 'formula'>('local')

  // 表单状态
  const [formData, setFormData] = useState<Partial<Note>>({
    title: '',
    content: '',
    type: 'note',
    tags: [],
    isFavorite: false
  })
  const [tagInput, setTagInput] = useState('')
  // 笔记面板宽度（默认560，min480/max860，持久化）+ 全屏切换
  const [noteWidth, setNoteWidth] = useState(() => {
    try {
      const saved = Number(localStorage.getItem('notePanelWidth'))
      if (Number.isFinite(saved) && saved >= 480 && saved <= 860) return saved
    } catch { /* ignore */ }
    return 560
  })
  const [noteFullscreen, setNoteFullscreen] = useState(false)

  // 公式识别弹窗（笔记编辑器「插入公式」）
  const [formulaOpen, setFormulaOpen] = useState(false)
  const [showKnowledgeTeam, setShowKnowledgeTeam] = useState(false)
  const [knowledgeTeamId, setKnowledgeTeamId] = useState('builtin-knowledge-synthesis')

  useEffect(() => {
    if (searchParams.get('action') !== 'knowledge-synthesis') return
    setKnowledgeTeamId(searchParams.get('teamId') || 'builtin-knowledge-synthesis')
    setShowKnowledgeTeam(true)
    const next = new URLSearchParams(searchParams)
    next.delete('action'); next.delete('teamId')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  // 派生数据
  const { stats, filteredNotes } = useKnowledgeData(notes, filterType, filterFavorite, searchQuery)
  const filteredObsidianFiles = useMemo(() => {
    const query = searchQuery.trim().toLocaleLowerCase()
    if (!query) return obsidianFiles
    return obsidianFiles.filter((file) =>
      file.title.toLocaleLowerCase().includes(query)
      || file.path.toLocaleLowerCase().includes(query)
      || file.tags.some((tag) => tag.toLocaleLowerCase().includes(query)),
    )
  }, [obsidianFiles, searchQuery])

  // 加载数据
  const loadData = useCallback(async () => {
    setIsLoading(true)
    try {
      const data = await fetchNotes()
      setNotes(data)
    } catch (error) {
      console.error('Failed to load data:', error)
      toast({ title: '加载失败', description: '无法加载笔记数据', variant: 'error' })
    } finally {
      setIsLoading(false)
    }
  }, [])

  // 加载 Obsidian 文件
  const loadObsidianFiles = useCallback(async (vaultId: number) => {
    setIsLoading(true)
    try {
      const files = await fetchVaultFiles(vaultId)
      setObsidianFiles(files)
    } catch (error) {
      console.error('Failed to load Obsidian files:', error)
    } finally {
      setIsLoading(false)
    }
  }, [])

  // 加载 Obsidian Vaults
  const loadObsidianVaults = useCallback(async () => {
    try {
      const vaults = await fetchVaults()
      setObsidianVaults(vaults)
      if (vaults.length > 0 && !selectedVaultRef.current) {
        selectedVaultRef.current = vaults[0].id
        setSelectedVault(vaults[0].id)
        void loadObsidianFiles(vaults[0].id)
      }
    } catch (error) {
      console.error('Failed to load Obsidian vaults:', error)
    }
  }, [loadObsidianFiles])

  useEffect(() => {
    void loadData()
    void loadObsidianVaults()
  }, [loadData, loadObsidianVaults])

  // 扫描 Vault
  const handleScanVault = async (vaultId: number) => {
    setIsScanning(true)
    try {
      const result = await scanVault(vaultId)
      if (result?.success) {
        toast({
          title: '扫描完成',
          description: `新增 ${result.added} 个文件，更新 ${result.updated} 个文件`,
          variant: 'success'
        })
        loadObsidianFiles(vaultId)
        loadObsidianVaults()
      }
    } catch (error) {
      toast({
        title: '扫描失败',
        description: error instanceof Error ? error.message : '无法扫描 Vault',
        variant: 'error'
      })
    } finally {
      setIsScanning(false)
    }
  }

  const handleOpenObsidianFile = async (file: ObsidianFile) => {
    const requestId = ++obsidianFileRequestRef.current
    setSelectedObsidianFile(file)
    setObsidianFileDetail(null)
    setObsidianFileError(null)
    setIsObsidianFileLoading(true)
    try {
      const detail = await fetchObsidianFile(file.id)
      if (requestId !== obsidianFileRequestRef.current) return
      if (!detail) {
        setObsidianFileError('文件不存在，或当前空间无权访问。请重新扫描 Vault 后再试。')
        return
      }
      setObsidianFileDetail(detail)
    } catch (error) {
      if (requestId !== obsidianFileRequestRef.current) return
      console.error('Failed to load Obsidian file:', error)
      setObsidianFileError('请求失败，请检查后端连接后重试。')
    } finally {
      if (requestId === obsidianFileRequestRef.current) setIsObsidianFileLoading(false)
    }
  }

  const closeObsidianFile = () => {
    obsidianFileRequestRef.current += 1
    setSelectedObsidianFile(null)
    setObsidianFileDetail(null)
    setObsidianFileError(null)
    setIsObsidianFileLoading(false)
  }

  // 从后端可见的服务器文件系统选择目录
  const handleSelectDirectory = (path: string, folderName: string) => {
    setVaultPathInput(path)
    if (!vaultNameInput.trim()) setVaultNameInput(folderName)
    toast({ title: '已选择服务端目录', description: path, variant: 'success' })
  }

  // 关闭 Vault 选择对话框并重置输入
  const closeVaultSelector = () => {
    setShowVaultSelector(false)
    setVaultPathInput('')
    setVaultNameInput('')
  }

  // 添加 Vault
  const handleAddVault = async () => {
    if (!vaultNameInput.trim() || !vaultPathInput.trim()) {
      toast({ title: '请填写完整信息', variant: 'error' })
      return
    }
    try {
      const result = await addVault(vaultNameInput, vaultPathInput)
      if (result) {
        if (result.success) {
          toast({ title: '添加成功', variant: 'success' })
          setVaultNameInput('')
          setVaultPathInput('')
          setShowVaultSelector(false)
          loadObsidianVaults()
        } else {
          toast({ title: result.message || '添加失败', variant: 'error' })
        }
      }
    } catch (error) {
      toast({
        title: '添加失败',
        description: error instanceof Error ? error.message : '无法添加 Vault',
        variant: 'error'
      })
    }
  }

  // 保存笔记
  const handleSaveNote = async () => {
    if (!formData.title?.trim()) {
      toast({ title: '请输入笔记标题', variant: 'error' })
      return
    }

    try {
      const ok = editingNote
        ? await updateNote(editingNote.id, formData)
        : await saveNote(formData)

      if (ok) {
        toast({
          title: editingNote ? '笔记已更新' : '笔记已创建',
          variant: 'success'
        })
        setShowEditor(false)
        setEditingNote(null)
        setFormData({ title: '', content: '', type: 'note', tags: [], isFavorite: false })
        loadData()
      }
    } catch (error) {
      console.error('Save note error:', error)
      toast({ title: '保存失败', variant: 'error' })
    }
  }

  // 删除笔记
  const handleDeleteNote = async () => {
    if (!deletingNote) return

    try {
      const ok = await deleteNoteApi(deletingNote.id)
      if (ok) {
        toast({ title: '笔记已删除', variant: 'success' })
        setDeletingNote(null)
        if (selectedNote?.id === deletingNote.id) setSelectedNote(null)
        loadData()
      }
    } catch (error) {
      console.error('Delete note error:', error)
      toast({ title: '删除失败', variant: 'error' })
    }
  }

  // 添加标签
  const handleAddTag = () => {
    if (tagInput.trim() && !formData.tags?.includes(tagInput.trim())) {
      setFormData({ ...formData, tags: [...(formData.tags || []), tagInput.trim()] })
      setTagInput('')
    }
  }

  return (
    <div className="flex flex-col h-screen">
      <Header
        title="知识库"
        actions={
          <>
          <HeaderAction
            icon={BrainCircuit}
            label="知识综合"
            onClick={() => setShowKnowledgeTeam(true)}
          />
          <HeaderAction
            icon={Plus}
            label="新建笔记"
            onClick={() => {
              setEditingNote(null)
              setFormData({ title: '', content: '', type: 'note', tags: [], isFavorite: false })
              setShowEditor(true)
            }}
          />
          </>
        }
      />

      {/* 标签切换 */}
      <div className="px-6 pt-4">
        <div className="flex items-center gap-2 border-b">
          <button
            className={cn(
              'px-4 py-2 text-sm font-medium transition-colors',
              activeTab === 'local'
                ? 'text-primary border-b-2 border-primary'
                : 'text-muted-foreground hover:text-foreground'
            )}
            onClick={() => setActiveTab('local')}
          >
            本地笔记
          </button>
          <button
            className={cn(
              'px-4 py-2 text-sm font-medium transition-colors flex items-center gap-2',
              activeTab === 'obsidian'
                ? 'text-primary border-b-2 border-primary'
                : 'text-muted-foreground hover:text-foreground'
            )}
            onClick={() => setActiveTab('obsidian')}
          >
            <Link2 className="w-4 h-4" />
            Obsidian
            {obsidianVaults.length > 0 && (
              <span className="text-xs bg-primary/10 text-primary px-1.5 py-0.5 rounded-full">
                {obsidianVaults.length}
              </span>
            )}
          </button>
          <button
            className={cn(
              'px-4 py-2 text-sm font-medium transition-colors flex items-center gap-2',
              activeTab === 'formula'
                ? 'text-primary border-b-2 border-primary'
                : 'text-muted-foreground hover:text-foreground'
            )}
            onClick={() => setActiveTab('formula')}
          >
            <FunctionSquare className="w-4 h-4" />
            公式工具
          </button>
        </div>
      </div>

      {activeTab === 'obsidian' && (
        <div className="px-6 py-4 bg-muted/30 border-b">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              {obsidianVaults.length === 0 ? (
                <div className="text-sm text-muted-foreground">暂无连接的 Obsidian Vault</div>
              ) : (
                <div className="flex items-center gap-2">
                  <select
                    className="px-3 py-1.5 text-sm border rounded-md bg-background"
                    value={selectedVault || ''}
                    onChange={(e) => {
                      const vaultId = parseInt(e.target.value)
                      closeObsidianFile()
                      setSelectedVault(vaultId)
                      loadObsidianFiles(vaultId)
                    }}
                  >
                    {obsidianVaults.map((vault) => (
                      <option key={vault.id} value={vault.id}>
                        {vault.name} ({vault.file_count} 文件)
                      </option>
                    ))}
                  </select>
                  {selectedVault && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleScanVault(selectedVault)}
                      disabled={isScanning}
                    >
                      <RefreshCw className={cn('w-4 h-4 mr-2', isScanning && 'animate-spin')} />
                      {isScanning ? '扫描中...' : '扫描'}
                    </Button>
                  )}
                </div>
              )}
            </div>
            <Button variant="outline" size="sm" onClick={() => setShowVaultSelector(true)}>
              <FolderOpen className="w-4 h-4 mr-2" />
              添加 Vault
            </Button>
          </div>
        </div>
      )}

      {activeTab === 'formula' ? (
        <div className="flex-1 overflow-hidden">
          <FormulaHub embedded />
        </div>
      ) : (
      <div className="flex-1 overflow-hidden flex">
        {/* 左侧列表 */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* 统计卡片 */}
          <div className="grid grid-cols-4 gap-4 p-6 pb-0">
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">总笔记</p>
                    <p className="text-2xl font-bold">{stats.total}</p>
                  </div>
                  <div className="p-3 bg-primary/10 rounded-full">
                    <BookOpen className="w-5 h-5 text-primary" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">想法</p>
                    <p className="text-2xl font-bold">{stats.byType.idea}</p>
                  </div>
                  <div className="p-3 bg-yellow-500/10 rounded-full">
                    <Lightbulb className="w-5 h-5 text-yellow-500" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">总结</p>
                    <p className="text-2xl font-bold">{stats.byType.summary}</p>
                  </div>
                  <div className="p-3 bg-green-500/10 rounded-full">
                    <FileText className="w-5 h-5 text-green-500" />
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">收藏</p>
                    <p className="text-2xl font-bold">{stats.favorite}</p>
                  </div>
                  <div className="p-3 bg-yellow-500/10 rounded-full">
                    <Star className="w-5 h-5 text-yellow-500" />
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* 搜索和筛选 */}
          <div className="px-6 py-4">
            <div className="flex items-center gap-4">
              <div className="relative flex-1 max-w-md">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder={activeTab === 'obsidian' ? '搜索 Obsidian 文件...' : '搜索笔记...'}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9"
                />
              </div>
              {activeTab === 'local' ? (
                <Button
                  variant="outline"
                  onClick={() => setShowFilters(!showFilters)}
                  className={showFilters ? 'bg-muted' : ''}
                >
                  <Filter className="w-4 h-4 mr-2" />
                  筛选
                </Button>
              ) : (
                <div className="flex items-center rounded-md border bg-background p-1">
                  <Button
                    type="button"
                    variant={obsidianViewMode === 'tree' ? 'secondary' : 'ghost'}
                    size="sm"
                    onClick={() => setObsidianViewMode('tree')}
                  >
                    <FolderOpen className="mr-1.5 h-4 w-4" />目录树
                  </Button>
                  <Button
                    type="button"
                    variant={obsidianViewMode === 'recent' ? 'secondary' : 'ghost'}
                    size="sm"
                    onClick={() => setObsidianViewMode('recent')}
                  >
                    <History className="mr-1.5 h-4 w-4" />最近修改
                  </Button>
                </div>
              )}
            </div>

            {activeTab === 'local' && showFilters && (
              <div className="flex flex-wrap items-center gap-4 mt-4 p-4 bg-muted/50 rounded-lg">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">类型:</span>
                  <select
                    className="h-9 px-3 rounded-md border border-input bg-background text-sm"
                    value={filterType}
                    onChange={(e) => setFilterType(e.target.value)}
                  >
                    <option value="all">全部</option>
                    {Object.entries(NOTE_TYPE_CONFIG).map(([value, config]) => (
                      <option key={value} value={value}>
                        {config.label}
                      </option>
                    ))}
                  </select>
                </div>
                <Button
                  variant={filterFavorite ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setFilterFavorite(!filterFavorite)}
                >
                  <Star className="w-4 h-4 mr-1" />
                  仅收藏
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setFilterType('all')
                    setFilterFavorite(false)
                    setSearchQuery('')
                  }}
                >
                  清除筛选
                </Button>
              </div>
            )}
          </div>

          {/* 笔记列表 */}
          <ScrollArea className="flex-1 px-6 pb-6">
            {activeTab === 'local' ? (
              // 本地笔记列表
              isLoading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
                </div>
              ) : filteredNotes.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground">
                  <BookOpen className="w-12 h-12 mx-auto mb-4 opacity-50" />
                  <p>暂无笔记</p>
                  <p className="text-sm mt-1">点击"新建笔记"开始记录你的知识</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {filteredNotes.map((note) => (
                    <NoteCard
                      key={note.id}
                      note={note}
                      isSelected={selectedNote?.id === note.id}
                      onSelect={setSelectedNote}
                    />
                  ))}
                </div>
              )
            ) : (
              // Obsidian 文件列表
              isLoading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
                </div>
              ) : obsidianFiles.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground">
                  <Link2 className="w-12 h-12 mx-auto mb-4 opacity-50" />
                  <p>暂无 Obsidian 文件</p>
                  <p className="text-sm mt-1">点击"扫描"按钮导入 Vault 中的笔记</p>
                </div>
              ) : filteredObsidianFiles.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground">
                  <Search className="w-12 h-12 mx-auto mb-4 opacity-50" />
                  <p>没有匹配的 Obsidian 文件</p>
                  <p className="text-sm mt-1">可按文件名、目录路径或标签搜索</p>
                </div>
              ) : (
                <ObsidianFileBrowser
                  key={selectedVault || 'no-vault'}
                  files={filteredObsidianFiles}
                  mode={obsidianViewMode}
                  selectedFileId={selectedObsidianFile?.id}
                  forceExpand={Boolean(searchQuery.trim())}
                  onOpen={(file) => void handleOpenObsidianFile(file)}
                />
              )
            )}
          </ScrollArea>
        </div>

        {/* 右侧详情/编辑器（可调宽 + 全屏） */}
        {activeTab === 'local' && (selectedNote || showEditor) && (
          <NoteEditor
            selectedNote={selectedNote}
            showEditor={showEditor}
            editingNote={editingNote}
            formData={formData}
            tagInput={tagInput}
            setEditingNote={setEditingNote}
            setFormData={setFormData}
            setShowEditor={setShowEditor}
            setDeletingNote={setDeletingNote}
            setTagInput={setTagInput}
            handleAddTag={handleAddTag}
            handleSaveNote={handleSaveNote}
            onInsertFormula={() => setFormulaOpen(true)}
            width={noteWidth}
            onWidthChange={(w) => {
              const clamped = Math.min(860, Math.max(480, Math.round(w)))
              setNoteWidth(clamped)
              try { localStorage.setItem('notePanelWidth', String(clamped)) } catch { /* ignore */ }
            }}
            fullscreen={noteFullscreen}
            onToggleFullscreen={() => setNoteFullscreen((v) => !v)}
          />
        )}
        {activeTab === 'obsidian' && selectedObsidianFile && (
          <ObsidianFileViewer
            file={selectedObsidianFile}
            detail={obsidianFileDetail}
            loading={isObsidianFileLoading}
            error={obsidianFileError}
            width={noteWidth}
            onRetry={() => void handleOpenObsidianFile(selectedObsidianFile)}
            onClose={closeObsidianFile}
          />
        )}
      </div>
      )}

      {/* 删除确认对话框 */}
      <ConfirmDialog
        isOpen={!!deletingNote}
        onClose={() => setDeletingNote(null)}
        onConfirm={handleDeleteNote}
        title="删除笔记"
        message={`确定要删除笔记 "${deletingNote?.title}" 吗？此操作不可恢复。`}
        confirmText="删除"
        cancelText="取消"
        variant="danger"
      />

      {/* 添加 Vault 对话框 */}
      {showVaultSelector && (
        <VaultSelectorDialog
          vaultNameInput={vaultNameInput}
          vaultPathInput={vaultPathInput}
          setVaultNameInput={setVaultNameInput}
          setVaultPathInput={setVaultPathInput}
          onSelectDirectory={handleSelectDirectory}
          onAddVault={handleAddVault}
          onClose={closeVaultSelector}
        />
      )}

      {/* 公式识别弹窗（识别成功后「插入到笔记」，LaTeX 写入正文） */}
      {formulaOpen && (
        <div
          className="fixed inset-0 z-[90] bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => setFormulaOpen(false)}
          aria-modal="true"
          role="dialog"
          aria-label="公式识别"
        >
          <div
            className="w-full max-w-4xl h-[80vh] glass rounded-2xl shadow-2xl border border-border/50 overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-3 border-b shrink-0">
              <div>
                <h3 className="font-display font-semibold flex items-center gap-2">
                  <FunctionSquare className="w-4 h-4 text-primary" />
                  公式识别 · 插入到笔记
                </h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  上传或粘贴公式图片，识别结果将插入笔记正文（$$...$$）
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setFormulaOpen(false)}
                aria-label="关闭"
              >
                <X className="w-5 h-5" />
              </Button>
            </div>
            <div className="flex-1 overflow-hidden">
              <FormulaHub
                embedded
                onInsert={(latex) => {
                  // 追加 LaTeX 到正文末尾（行间公式块）
                  const block = `\n\n$$\n${latex}\n$$\n`
                  setFormData((prev) => ({
                    ...prev,
                    content: `${prev.content || ''}${block}`,
                  }))
                  setFormulaOpen(false)
                }}
              />
            </div>
          </div>
        </div>
      )}

      {showKnowledgeTeam && (
        <TeamContextRunDialog
          kind="notes"
          entities={notes.map(note => ({ id: note.id, title: note.title }))}
          initialIds={selectedNote ? [selectedNote.id] : []}
          defaultTeamId={knowledgeTeamId}
          applyLabel="保存为新的 AI 笔记"
          onClose={() => setShowKnowledgeTeam(false)}
          onApply={async output => {
            const report = output as { title?: string; markdown?: string; tags?: string[] }
            const ok = await saveNote({
              title: report.title || '知识综合',
              content: report.markdown || JSON.stringify(output, null, 2),
              type: 'note', tags: report.tags || ['AI综合'], aiGenerated: true
            })
            if (ok) {
              toast({ title: '已保存新的 AI 笔记', variant: 'success' })
              setShowKnowledgeTeam(false)
              await loadData()
            } else {
              toast({ title: '保存失败', variant: 'error' })
            }
          }}
        />
      )}
    </div>
  )
}
