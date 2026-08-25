// NoteEditor component for the Knowledge Hub.
// Extracted from the original monolithic index.tsx view/edit panel (lines 643-796).
// It is a controlled presentational component: the container owns all state and
// passes the setters + handlers down, so the rendered JSX is identical to the source.

import { Dispatch, SetStateAction } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { MarkdownEditor, MarkdownPreview } from '@/components/ui/markdown-editor'
import { Edit2, Trash2, FunctionSquare } from 'lucide-react'
import type { Note } from '@/types'
import { NOTE_TYPE_CONFIG } from '../config'

interface NoteEditorProps {
  selectedNote: Note | null
  showEditor: boolean
  editingNote: Note | null
  formData: Partial<Note>
  tagInput: string
  setEditingNote: Dispatch<SetStateAction<Note | null>>
  setFormData: Dispatch<SetStateAction<Partial<Note>>>
  setShowEditor: Dispatch<SetStateAction<boolean>>
  setDeletingNote: Dispatch<SetStateAction<Note | null>>
  setTagInput: Dispatch<SetStateAction<string>>
  handleAddTag: () => void
  handleSaveNote: () => void
  /** 打开公式识别弹窗，识别结果插入笔记正文 */
  onInsertFormula?: () => void
}

/** Right-hand panel showing either a note preview or the create/edit form. */
export function NoteEditor({
  selectedNote,
  showEditor,
  editingNote,
  formData,
  tagInput,
  setEditingNote,
  setFormData,
  setShowEditor,
  setDeletingNote,
  setTagInput,
  handleAddTag,
  handleSaveNote,
  onInsertFormula
}: NoteEditorProps) {
  return (
    <div className="w-[480px] border-l bg-muted/30 overflow-y-auto">
      <div className="p-6">
        {/* 查看模式 */}
        {selectedNote && !showEditor && (
          <>
            <div className="flex items-center justify-between mb-4">
              <Badge className={NOTE_TYPE_CONFIG[selectedNote.type]?.color || 'bg-blue-500'}>
                {NOTE_TYPE_CONFIG[selectedNote.type]?.label || '笔记'}
              </Badge>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setEditingNote(selectedNote)
                    setFormData(selectedNote)
                    setShowEditor(true)
                  }}
                >
                  <Edit2 className="w-4 h-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-red-500"
                  onClick={() => setDeletingNote(selectedNote)}
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            </div>

            <h2 className="text-xl font-bold mb-4">{selectedNote.title}</h2>

            <div className="mb-6">
              {selectedNote.content ? (
                <MarkdownPreview content={selectedNote.content} />
              ) : (
                <p className="text-muted-foreground">暂无内容</p>
              )}
            </div>

            {selectedNote.tags && selectedNote.tags.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-4">
                {selectedNote.tags.map((tag) => (
                  <Badge key={tag} variant="secondary">
                    {tag}
                  </Badge>
                ))}
              </div>
            )}

            <p className="text-xs text-muted-foreground">
              创建于 {new Date(selectedNote.createdAt).toLocaleString('zh-CN')}
            </p>
          </>
        )}

        {/* 编辑模式 */}
        {showEditor && (
          <>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold">{editingNote ? '编辑笔记' : '新建笔记'}</h3>
              <Button variant="ghost" size="sm" onClick={() => setShowEditor(false)}>
                取消
              </Button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="text-sm font-medium mb-2 block">标题 *</label>
                <Input
                  placeholder="输入笔记标题..."
                  value={formData.title}
                  onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                />
              </div>

              <div>
                <label className="text-sm font-medium mb-2 block">类型</label>
                <div className="flex gap-2">
                  {Object.entries(NOTE_TYPE_CONFIG).map(([value, config]) => (
                    <button
                      key={value}
                      onClick={() => setFormData({ ...formData, type: value as Note['type'] })}
                      className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition-colors ${
                        formData.type === value
                          ? 'bg-primary text-primary-foreground border-primary'
                          : 'bg-background hover:bg-muted'
                      }`}
                    >
                      <config.icon className="w-4 h-4" />
                      <span className="text-sm">{config.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-sm font-medium mb-2 block">内容</label>
                <MarkdownEditor
                  value={formData.content || ''}
                  onChange={(value) => setFormData({ ...formData, content: value })}
                  height={300}
                  toolbarExtra={
                    onInsertFormula ? (
                      <Button variant="ghost" size="sm" onClick={onInsertFormula}>
                        <FunctionSquare className="w-4 h-4 mr-2" />
                        插入公式
                      </Button>
                    ) : undefined
                  }
                />
              </div>

              <div>
                <label className="text-sm font-medium mb-2 block">标签</label>
                <div className="flex gap-2 mb-2">
                  <Input
                    placeholder="添加标签..."
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), handleAddTag())}
                  />
                  <Button type="button" onClick={handleAddTag}>
                    添加
                  </Button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {formData.tags?.map((tag) => (
                    <Badge
                      key={tag}
                      variant="secondary"
                      className="cursor-pointer"
                      onClick={() => {
                        setFormData({ ...formData, tags: formData.tags?.filter((t) => t !== tag) })
                      }}
                    >
                      {tag} ×
                    </Badge>
                  ))}
                </div>
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="isFavorite"
                  checked={formData.isFavorite}
                  onChange={(e) => setFormData({ ...formData, isFavorite: e.target.checked })}
                />
                <label htmlFor="isFavorite" className="text-sm">
                  收藏此笔记
                </label>
              </div>

              <div className="flex justify-end gap-2 pt-4">
                <Button variant="outline" onClick={() => setShowEditor(false)}>
                  取消
                </Button>
                <Button onClick={handleSaveNote}>{editingNote ? '保存' : '创建'}</Button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
