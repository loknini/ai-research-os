/**
 * Paper Hub 的「抓取论文设置」对话框（关键词 + 抓取数量）。
 * 源自原 monolith index.tsx 843–910 行，抽离为受控弹窗组件。
 *
 * 组件读取并写入 fetchDialog.keywords / fetchDialog.maxResults，
 * 提交时调用容器传入的 handleFetchPapers。
 * 额外接收 isFetching 以保留「抓取中禁用 + 旋转图标」的原始行为。
 */

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Plus, RefreshCw } from 'lucide-react'

export interface FetchDialogState {
  isOpen: boolean
  keywords: string
  maxResults: number
}

export interface FetchPapersDialogProps {
  fetchDialog: FetchDialogState
  setFetchDialog: (state: FetchDialogState) => void
  handleFetchPapers: () => void
  /** 抓取进行中（保留原 monolith 的禁用 + 旋转图标行为） */
  isFetching: boolean
}

export default function FetchPapersDialog({
  fetchDialog,
  setFetchDialog,
  handleFetchPapers,
  isFetching
}: FetchPapersDialogProps) {
  if (!fetchDialog.isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-background rounded-lg shadow-lg w-full max-w-md mx-4">
        <div className="p-6">
          <h2 className="text-lg font-semibold mb-4">抓取论文设置</h2>

          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-2 block">
                搜索关键词（用逗号分隔）
              </label>
              <Input
                placeholder="例如: object detection, transformer, attention..."
                value={fetchDialog.keywords}
                onChange={(e) => setFetchDialog({ ...fetchDialog, keywords: e.target.value })}
              />
              <p className="text-xs text-muted-foreground mt-1">
                留空则抓取所有 CV 论文
              </p>
            </div>

            <div>
              <label className="text-sm font-medium mb-2 block">
                抓取数量
              </label>
              <Input
                type="number"
                min={1}
                max={50}
                value={fetchDialog.maxResults}
                onChange={(e) =>
                  setFetchDialog({ ...fetchDialog, maxResults: parseInt(e.target.value) || 10 })
                }
              />
              <p className="text-xs text-muted-foreground mt-1">
                最多 50 篇
              </p>
            </div>
          </div>

          <div className="flex justify-end gap-3 mt-6">
            <Button
              variant="outline"
              onClick={() => setFetchDialog({ ...fetchDialog, isOpen: false })}
            >
              取消
            </Button>
            <Button onClick={handleFetchPapers} disabled={isFetching}>
              {isFetching ? (
                <>
                  <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  抓取中...
                </>
              ) : (
                <>
                  <Plus className="w-4 h-4 mr-2" />
                  {fetchDialog.keywords.trim()
                    ? `搜索 "${fetchDialog.keywords.trim().substring(0, 20)}${
                        fetchDialog.keywords.trim().length > 20 ? '...' : ''
                      }"`
                    : '抓取最新 CV 论文'}
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
