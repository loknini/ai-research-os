import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiRequest = vi.hoisted(() => vi.fn())

vi.mock('@/services/api', () => ({ apiRequest }))

import { fetchObsidianFile } from './obsidianApi'

describe('obsidianApi', () => {
  beforeEach(() => apiRequest.mockReset())

  it('loads a complete Obsidian file from its detail endpoint', async () => {
    const file = {
      id: 7,
      path: 'research/note.md',
      title: 'note',
      content: '# Note',
      frontmatter: { status: 'draft' },
      tags: ['rag'],
      links: [{ target: 'other-note', alias: 'Other Note' }],
      modified_at: 123,
    }
    apiRequest.mockResolvedValue(new Response(JSON.stringify({ success: true, file }), { status: 200 }))

    await expect(fetchObsidianFile(7)).resolves.toEqual(file)
    expect(apiRequest).toHaveBeenCalledWith('/api/obsidian/files/7')
  })

  it('returns null for missing files and failed responses', async () => {
    apiRequest
      .mockResolvedValueOnce(new Response(JSON.stringify({ success: true, file: null }), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 404 }))

    await expect(fetchObsidianFile(8)).resolves.toBeNull()
    await expect(fetchObsidianFile(9)).resolves.toBeNull()
  })
})
