// Derived data hook for the Knowledge Hub.
// Extracted from the original monolithic index.tsx (stats useMemo at 228-237 and
// filteredNotes useMemo at 240-247). Returns the memoized derived values so the
// container no longer holds the inline useMemo blocks.

import { useMemo } from 'react'
import type { Note } from '@/types'

/**
 * Compute derived note statistics and the filtered note list.
 *
 * @param notes          Full list of local notes.
 * @param filterType     Selected type filter ('all' or a NoteType value).
 * @param filterFavorite Whether only favorite notes should be shown.
 * @param searchQuery    Free-text search against the note title.
 */
export function useKnowledgeData(
  notes: Note[],
  filterType: string,
  filterFavorite: boolean,
  searchQuery: string
) {
  const stats = useMemo(
    () => ({
      total: notes.length,
      byType: {
        note: notes.filter((n) => n.type === 'note').length,
        idea: notes.filter((n) => n.type === 'idea').length,
        summary: notes.filter((n) => n.type === 'summary').length,
        code_snippet: notes.filter((n) => n.type === 'code_snippet').length
      },
      favorite: notes.filter((n) => n.isFavorite).length
    }),
    [notes]
  )

  const filteredNotes = useMemo(() => {
    return notes.filter((note) => {
      if (filterType !== 'all' && note.type !== filterType) return false
      if (filterFavorite && !note.isFavorite) return false
      if (searchQuery && !note.title.toLowerCase().includes(searchQuery.toLowerCase())) return false
      return true
    })
  }, [notes, filterType, filterFavorite, searchQuery])

  return { stats, filteredNotes }
}
