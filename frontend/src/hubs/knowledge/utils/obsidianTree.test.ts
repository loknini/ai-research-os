import { describe, expect, it } from 'vitest'
import type { ObsidianFile } from '../types'
import { buildObsidianTree, collectObsidianDirectoryPaths } from './obsidianTree'

function file(id: number, path: string): ObsidianFile {
  return { id, path, title: path.replace(/^.*[\\/]/, '').replace(/\.md$/, ''), tags: [], modified_at: id }
}

describe('buildObsidianTree', () => {
  it('reconstructs mixed Windows and POSIX relative paths', () => {
    const tree = buildObsidianTree([
      file(1, '1-Project\\12-Job\\algorithm.md'),
      file(2, '1-Project/notes.md'),
      file(3, 'root.md'),
    ])

    expect(tree.map((node) => [node.kind, node.name])).toEqual([
      ['directory', '1-Project'],
      ['file', 'root.md'],
    ])
    expect(collectObsidianDirectoryPaths(tree)).toEqual(['1-Project', '1-Project/12-Job'])
    const project = tree[0]
    expect(project.kind).toBe('directory')
    if (project.kind === 'directory') {
      expect(project.children.map((node) => node.name)).toEqual(['12-Job', 'notes.md'])
    }
  })

  it('sorts folders before files using natural name order', () => {
    const tree = buildObsidianTree([
      file(1, 'folder10/a.md'),
      file(2, 'z.md'),
      file(3, 'folder2/b.md'),
      file(4, 'a.md'),
    ])

    expect(tree.map((node) => node.name)).toEqual(['folder2', 'folder10', 'a.md', 'z.md'])
  })
})
