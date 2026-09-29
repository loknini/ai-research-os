import { useMemo, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  FileText,
  Folder,
  FolderOpen,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/utils'
import type { ObsidianFile } from '../types'
import {
  buildObsidianTree,
  collectObsidianDirectoryPaths,
  countObsidianFiles,
  type ObsidianTreeNode,
} from '../utils/obsidianTree'

interface ObsidianFileBrowserProps {
  files: ObsidianFile[]
  mode: 'tree' | 'recent'
  selectedFileId?: number
  forceExpand?: boolean
  onOpen: (file: ObsidianFile) => void
}

function ModifiedDate({ timestamp }: { timestamp: number }) {
  return (
    <span className="shrink-0 text-xs text-muted-foreground">
      {new Date(timestamp * 1000).toLocaleDateString('zh-CN')}
    </span>
  )
}

export function ObsidianFileBrowser({
  files,
  mode,
  selectedFileId,
  forceExpand = false,
  onOpen,
}: ObsidianFileBrowserProps) {
  const tree = useMemo(() => buildObsidianTree(files), [files])
  const directoryPaths = useMemo(() => collectObsidianDirectoryPaths(tree), [tree])
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(
    () => new Set(tree.filter((node) => node.kind === 'directory').map((node) => node.path)),
  )

  const toggleDirectory = (path: string) => {
    setExpandedPaths((current) => {
      const next = new Set(current)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const renderTreeNodes = (nodes: ObsidianTreeNode[], depth = 0): React.ReactNode =>
    nodes.map((node) => {
      if (node.kind === 'directory') {
        const expanded = forceExpand || expandedPaths.has(node.path)
        return (
          <div key={`directory:${node.path}`}>
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-md py-2 pr-3 text-left hover:bg-muted/60"
              style={{ paddingLeft: `${depth * 20 + 8}px` }}
              onClick={() => toggleDirectory(node.path)}
              aria-expanded={expanded}
            >
              {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              {expanded ? (
                <FolderOpen className="h-4 w-4 text-amber-500" />
              ) : (
                <Folder className="h-4 w-4 text-amber-500" />
              )}
              <span className="min-w-0 flex-1 truncate font-medium">{node.name}</span>
              <span className="text-xs text-muted-foreground">{countObsidianFiles(node)}</span>
            </button>
            {expanded && renderTreeNodes(node.children, depth + 1)}
          </div>
        )
      }

      return (
        <button
          type="button"
          key={`file:${node.file.id}`}
          className={cn(
            'flex w-full items-center gap-2 rounded-md py-2 pr-3 text-left hover:bg-muted/60',
            selectedFileId === node.file.id && 'bg-primary/10 text-primary',
          )}
          style={{ paddingLeft: `${depth * 20 + 32}px` }}
          onClick={() => onOpen(node.file)}
          aria-pressed={selectedFileId === node.file.id}
          title={node.file.path}
        >
          <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate">{node.file.title}</span>
          <ModifiedDate timestamp={node.file.modified_at} />
        </button>
      )
    })

  if (mode === 'tree') {
    return (
      <div className="rounded-lg border bg-background">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <span className="text-xs text-muted-foreground">{files.length} 个 Markdown 文件</span>
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={forceExpand}
              onClick={() => setExpandedPaths(new Set(directoryPaths))}
            >
              <ChevronsUpDown className="mr-1 h-3.5 w-3.5" />全部展开
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={forceExpand}
              onClick={() => setExpandedPaths(new Set())}
            >
              <ChevronsDownUp className="mr-1 h-3.5 w-3.5" />全部折叠
            </Button>
          </div>
        </div>
        <div className="p-2">{renderTreeNodes(tree)}</div>
      </div>
    )
  }

  const recentFiles = [...files].sort((left, right) => right.modified_at - left.modified_at)
  return (
    <div className="space-y-2">
      {recentFiles.map((file) => (
        <button
          type="button"
          key={file.id}
          className={cn(
            'w-full rounded-lg border p-4 text-left transition-colors hover:bg-muted/50',
            selectedFileId === file.id && 'border-primary bg-primary/5',
          )}
          onClick={() => onOpen(file)}
          aria-pressed={selectedFileId === file.id}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <h3 className="truncate font-medium">{file.title}</h3>
              <p className="mt-1 truncate text-sm text-muted-foreground">{file.path}</p>
              {file.tags?.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {file.tags.map((tag) => (
                    <Badge key={tag} variant="secondary" className="text-xs">#{tag}</Badge>
                  ))}
                </div>
              )}
            </div>
            <ModifiedDate timestamp={file.modified_at} />
          </div>
        </button>
      ))}
    </div>
  )
}
