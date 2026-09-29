import { useCallback, useEffect, useState } from 'react'
import { ArrowUp, Check, ChevronRight, Folder, HardDrive, RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/utils'
import { browseServerDirectories } from '../services/obsidianApi'
import type { ServerDirectoryListing } from '../types'

interface ServerDirectoryPickerProps {
  selectedPath: string
  onSelect: (path: string, name: string) => void
}

function directoryName(path: string): string {
  const parts = path.replace(/[\\/]+$/, '').split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] || path
}

/** Browses directories on the backend machine; no browser-local path is inferred. */
export function ServerDirectoryPicker({ selectedPath, onSelect }: ServerDirectoryPickerProps) {
  const [listing, setListing] = useState<ServerDirectoryListing | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (path?: string) => {
    setLoading(true)
    setError(null)
    try {
      setListing(await browseServerDirectories(path))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法浏览服务器目录')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const currentPath = listing?.currentPath || null

  return (
    <section className="rounded-lg border bg-muted/20">
      <div className="flex items-center gap-2 border-b p-3">
        <Button type="button" variant="outline" size="sm" onClick={() => void load()}>
          <HardDrive className="mr-1.5 h-4 w-4" />根目录
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!listing?.parentPath || loading}
          onClick={() => void load(listing?.parentPath || undefined)}
        >
          <ArrowUp className="mr-1.5 h-4 w-4" />上一级
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          disabled={loading}
          onClick={() => void load(currentPath || undefined)}
          aria-label="刷新服务器目录"
        >
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
        </Button>
        <code className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={currentPath || '服务器根目录'}>
          {currentPath || '服务器根目录'}
        </code>
      </div>

      {error ? (
        <div className="p-5 text-center text-sm text-destructive">
          <p>{error}</p>
          <p className="mt-1 text-xs text-muted-foreground">远程访问时，请先在设置页解锁系统管理权限。</p>
        </div>
      ) : (
        <div className="max-h-56 overflow-y-auto p-2">
          {!loading && listing?.directories.length === 0 && (
            <p className="p-4 text-center text-sm text-muted-foreground">该目录没有可浏览的子目录</p>
          )}
          {listing?.directories.map((directory) => (
            <button
              type="button"
              key={directory.path}
              className={cn(
                'flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-muted',
                selectedPath === directory.path && 'bg-primary/10 text-primary',
              )}
              onClick={() => void load(directory.path)}
              title={directory.path}
            >
              {currentPath === null ? <HardDrive className="h-4 w-4" /> : <Folder className="h-4 w-4" />}
              <span className="min-w-0 flex-1 truncate">{directory.name}</span>
              {directory.isVault && <Badge variant="secondary">Vault</Badge>}
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            </button>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between gap-3 border-t p-3">
        <p className="text-xs text-muted-foreground">进入目标 Vault 后选择当前目录</p>
        <Button
          type="button"
          size="sm"
          disabled={!currentPath || loading}
          onClick={() => currentPath && onSelect(currentPath, directoryName(currentPath))}
        >
          <Check className="mr-1.5 h-4 w-4" />选择当前目录
        </Button>
      </div>
    </section>
  )
}
