// NoteCard component for the Knowledge Hub.
// Extracted from the original monolithic index.tsx renderNoteCard helper (lines 309-350).

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Star } from 'lucide-react'
import type { Note } from '@/types'
import { NOTE_TYPE_CONFIG } from '../config'

interface NoteCardProps {
  note: Note
  isSelected: boolean
  onSelect: (note: Note) => void
}

/** A single note rendered as a clickable card in the local notes list. */
export function NoteCard({ note, isSelected, onSelect }: NoteCardProps) {
  const typeConfig = NOTE_TYPE_CONFIG[note.type] || NOTE_TYPE_CONFIG.note
  const TypeIcon = typeConfig.icon

  return (
    <Card
      className={`cursor-pointer transition-all hover:shadow-md ${
        isSelected ? 'ring-2 ring-primary' : ''
      }`}
      onClick={() => onSelect(note)}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <div className={`p-1.5 rounded ${typeConfig.color} bg-opacity-10`}>
              <TypeIcon className={`w-4 h-4 ${typeConfig.color.replace('bg-', 'text-')}`} />
            </div>
            {note.isFavorite && <Star className="w-4 h-4 text-yellow-500 fill-yellow-500" />}
          </div>
          <Badge variant="secondary" className="text-xs">
            {typeConfig.label}
          </Badge>
        </div>
        <CardTitle className="text-base mt-2 line-clamp-2">{note.title}</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <p className="text-sm text-muted-foreground line-clamp-2 mb-3">
          {note.content || '暂无内容'}
        </p>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <div className="flex flex-wrap gap-1">
            {note.tags?.slice(0, 3).map((tag) => (
              <span key={tag} className="px-1.5 py-0.5 bg-muted rounded">
                {tag}
              </span>
            ))}
          </div>
          <span>{new Date(note.updatedAt).toLocaleDateString('zh-CN')}</span>
        </div>
      </CardContent>
    </Card>
  )
}
