import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { MarkdownPreview } from '@/components/ui/markdown-editor'
import { FileText, Link2, RefreshCw, X } from 'lucide-react'
import type { ObsidianFile, ObsidianFileDetail } from '../types'

interface ObsidianFileViewerProps {
  file: ObsidianFile
  detail: ObsidianFileDetail | null
  loading: boolean
  error: string | null
  width?: number
  onRetry: () => void
  onClose: () => void
}

/** Read-only detail panel for a file indexed from an Obsidian vault. */
export function ObsidianFileViewer({
  file,
  detail,
  loading,
  error,
  width = 560,
  onRetry,
  onClose,
}: ObsidianFileViewerProps) {
  return (
    <aside className="h-full flex-shrink-0 border-l bg-muted/30 flex flex-col" style={{ width }}>
      <div className="flex items-start justify-between gap-4 border-b p-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-medium text-primary">
            <Link2 className="h-3.5 w-3.5" />
            Obsidian
          </div>
          <h2 className="mt-1 truncate text-lg font-semibold">{file.title}</h2>
          <p className="mt-1 truncate text-xs text-muted-foreground" title={file.path}>{file.path}</p>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="关闭 Obsidian 文件详情">
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
            正在读取文件…
          </div>
        ) : error ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <FileText className="mb-3 h-10 w-10 text-muted-foreground/50" />
            <p className="text-sm font-medium">无法读取文件</p>
            <p className="mt-1 max-w-sm text-xs text-muted-foreground">{error}</p>
            <Button className="mt-4" variant="outline" size="sm" onClick={onRetry}>重试</Button>
          </div>
        ) : detail ? (
          <div className="space-y-6">
            <div className="flex flex-wrap gap-2">
              {detail.tags.map((tag) => <Badge key={tag} variant="secondary">#{tag}</Badge>)}
              <span className="self-center text-xs text-muted-foreground">
                更新于 {new Date(detail.modified_at * 1000).toLocaleString('zh-CN')}
              </span>
            </div>

            {Object.keys(detail.frontmatter).length > 0 && (
              <section>
                <h3 className="mb-2 text-sm font-semibold">Frontmatter</h3>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-lg border bg-background/60 p-3 text-xs">
                  {Object.entries(detail.frontmatter).map(([key, value]) => (
                    <div className="contents" key={key}>
                      <dt className="font-medium text-muted-foreground">{key}</dt>
                      <dd className="min-w-0 break-words">{typeof value === 'string' ? value : JSON.stringify(value)}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}

            <section>
              <h3 className="mb-3 text-sm font-semibold">正文</h3>
              {detail.content ? (
                <div className="prose max-w-none rounded-lg border bg-background p-4">
                  <MarkdownPreview content={detail.content} />
                </div>
              ) : (
                <p className="rounded-lg border p-4 text-sm text-muted-foreground">
                  文件已被索引，但当前无法从磁盘读取正文。请确认 Vault 路径仍然可用后重新扫描。
                </p>
              )}
            </section>

            {detail.links.length > 0 && (
              <section>
                <h3 className="mb-2 text-sm font-semibold">链接</h3>
                <div className="flex flex-wrap gap-2">
                  {detail.links.map((link) => (
                    <Badge key={`${link.target}:${link.alias}`} variant="outline" title={link.target}>
                      {link.alias}
                    </Badge>
                  ))}
                </div>
              </section>
            )}
          </div>
        ) : null}
      </div>
    </aside>
  )
}
