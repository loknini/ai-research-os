// Notes API service for the Knowledge Hub.
// Extracted from the original monolithic index.tsx (fetch calls inside loadData /
// handleSaveNote / handleDeleteNote at lines 87, 257-264, 287).
//
// Behavior contract: each function owns exactly one fetch request (URL, options and
// JSON parsing). They do NOT show toasts or mutate state — that stays in the
// container handlers. Non-OK responses are mapped to a safe default so the handler's
// existing `if (ok)` / `catch` flow reproduces the original behavior word-for-word.

import type { Note } from '@/types'

/**
 * Fetch the list of local notes.
 * Mirrors `loadData`: on success returns `data.notes`, otherwise an empty array
 * (matching the container's initial `[]` state so a failed load is a no-op).
 */
export async function fetchNotes(): Promise<Note[]> {
  const response = await fetch('/api/notes')
  if (response.ok) {
    const data = await response.json()
    if (data.success) return data.notes as Note[]
  }
  return []
}

/** Create a new note. Returns whether the request succeeded (response.ok). */
export async function saveNote(formData: Partial<Note>): Promise<boolean> {
  const response = await fetch('/api/notes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formData)
  })
  return response.ok
}

/** Update an existing note. Returns whether the request succeeded (response.ok). */
export async function updateNote(id: string, formData: Partial<Note>): Promise<boolean> {
  const response = await fetch(`/api/notes/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formData)
  })
  return response.ok
}

/** Delete a note by id. Returns whether the request succeeded (response.ok). */
export async function deleteNoteApi(id: string): Promise<boolean> {
  const response = await fetch(`/api/notes/${id}`, { method: 'DELETE' })
  return response.ok
}
