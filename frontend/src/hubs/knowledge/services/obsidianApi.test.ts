import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiRequest = vi.hoisted(() => vi.fn())

vi.mock('@/services/api', () => ({ apiRequest }))

import { browseServerDirectories, fetchObsidianFile } from './obsidianApi'

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

  it('browses server directories and safely encodes absolute paths', async () => {
    const listing = {
      success: true,
      currentPath: 'D:\\Notes & Papers',
      parentPath: 'D:\\',
      directories: [{ name: 'Vault', path: 'D:\\Notes & Papers\\Vault', isVault: true }],
    }
    apiRequest.mockResolvedValue(new Response(JSON.stringify(listing), { status: 200 }))

    await expect(browseServerDirectories('D:\\Notes & Papers')).resolves.toEqual(listing)
    expect(apiRequest).toHaveBeenCalledWith('/api/obsidian/directories?path=D%3A%5CNotes+%26+Papers')
  })

  it('surfaces server directory browsing errors', async () => {
    apiRequest.mockResolvedValue(new Response(JSON.stringify({ detail: '没有权限读取该目录' }), { status: 403 }))

    await expect(browseServerDirectories('D:\\Protected')).rejects.toThrow('没有权限读取该目录')
  })
})
