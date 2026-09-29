import type { ObsidianFile } from '../types'

export interface ObsidianFileNode {
  kind: 'file'
  name: string
  path: string
  file: ObsidianFile
}

export interface ObsidianDirectoryNode {
  kind: 'directory'
  name: string
  path: string
  children: ObsidianTreeNode[]
}

export type ObsidianTreeNode = ObsidianFileNode | ObsidianDirectoryNode

function compareNodes(left: ObsidianTreeNode, right: ObsidianTreeNode): number {
  if (left.kind !== right.kind) return left.kind === 'directory' ? -1 : 1
  return left.name.localeCompare(right.name, 'zh-CN', { numeric: true, sensitivity: 'base' })
}

function sortTree(nodes: ObsidianTreeNode[]): void {
  nodes.sort(compareNodes)
  for (const node of nodes) {
    if (node.kind === 'directory') sortTree(node.children)
  }
}

/** Build a display tree from the relative paths persisted by the Vault scanner. */
export function buildObsidianTree(files: ObsidianFile[]): ObsidianTreeNode[] {
  const root: ObsidianTreeNode[] = []

  for (const file of files) {
    const parts = file.path.split(/[\\/]+/).filter(Boolean)
    if (parts.length === 0) continue

    let children = root
    let parentPath = ''
    for (const segment of parts.slice(0, -1)) {
      const directoryPath = parentPath ? `${parentPath}/${segment}` : segment
      let directory = children.find(
        (node): node is ObsidianDirectoryNode =>
          node.kind === 'directory' && node.name === segment,
      )
      if (!directory) {
        directory = { kind: 'directory', name: segment, path: directoryPath, children: [] }
        children.push(directory)
      }
      children = directory.children
      parentPath = directoryPath
    }

    children.push({
      kind: 'file',
      name: parts[parts.length - 1],
      path: file.path,
      file,
    })
  }

  sortTree(root)
  return root
}

export function collectObsidianDirectoryPaths(nodes: ObsidianTreeNode[]): string[] {
  const paths: string[] = []
  for (const node of nodes) {
    if (node.kind !== 'directory') continue
    paths.push(node.path)
    paths.push(...collectObsidianDirectoryPaths(node.children))
  }
  return paths
}

export function countObsidianFiles(node: ObsidianDirectoryNode): number {
  return node.children.reduce(
    (total, child) => total + (child.kind === 'file' ? 1 : countObsidianFiles(child)),
    0,
  )
}
