// VaultSelectorDialog component for the Knowledge Hub.
// Extracted from the original monolithic index.tsx add-Vault dialog (lines 812-907).
// Controlled presentational component: the container owns all state and passes the
// setters + handlers (including the File System Access API picker) down.

import { Dispatch, SetStateAction } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/utils'
import { FolderOpen } from 'lucide-react'

interface VaultSelectorDialogProps {
  vaultNameInput: string
  vaultPathInput: string
  setVaultNameInput: Dispatch<SetStateAction<string>>
  setVaultPathInput: Dispatch<SetStateAction<string>>
  onSelectDirectory: () => void
  onAddVault: () => void
  onClose: () => void
}

/** Modal dialog for connecting a new Obsidian Vault (folder picker + manual path). */
export function VaultSelectorDialog({
  vaultNameInput,
  vaultPathInput,
  setVaultNameInput,
  setVaultPathInput,
  onSelectDirectory,
  onAddVault,
  onClose
}: VaultSelectorDialogProps) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-background rounded-lg p-6 w-[600px] max-w-[90vw]">
        <h3 className="text-lg font-semibold mb-4">添加 Obsidian Vault</h3>
        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-2 block">Vault 名称</label>
            <Input
              placeholder="例如：研究笔记"
              value={vaultNameInput}
              onChange={(e) => setVaultNameInput(e.target.value)}
            />
          </div>

          {/* 拖拽区域 */}
          <div
            className={cn(
              'border-2 border-dashed rounded-lg p-6 text-center transition-colors',
              'hover:border-primary/50 hover:bg-muted/50',
              vaultPathInput ? 'border-primary bg-primary/5' : 'border-muted-foreground/25'
            )}
            onDragOver={(e) => {
              e.preventDefault()
              e.stopPropagation()
            }}
            onDrop={(e) => {
              e.preventDefault()
              e.stopPropagation()

              const items = e.dataTransfer.items
              if (items.length > 0) {
                const item = items[0]
                if (item.kind === 'file') {
                  const entry = item.webkitGetAsEntry()
                  if (entry && entry.isDirectory) {
                    // 使用 File System Access API 获取路径
                    onSelectDirectory()
                  }
                }
              }
            }}
          >
            <FolderOpen className="w-10 h-10 mx-auto mb-3 text-muted-foreground" />
            <p className="text-sm font-medium mb-1">
              {vaultPathInput ? '已选择文件夹' : '拖拽文件夹到此处'}
            </p>
            <p className="text-xs text-muted-foreground mb-3">
              {vaultPathInput ? vaultPathInput : '或点击下方按钮选择'}
            </p>

            {/* 选择文件夹按钮 */}
            <Button
              variant="outline"
              size="sm"
              onClick={onSelectDirectory}
              disabled={!('showDirectoryPicker' in window)}
            >
              <FolderOpen className="w-4 h-4 mr-2" />
              {'showDirectoryPicker' in window ? '选择文件夹' : '浏览器不支持'}
            </Button>

            {!('showDirectoryPicker' in window) && (
              <p className="text-xs text-amber-600 mt-2">请使用 Chrome/Edge 浏览器以获得最佳体验</p>
            )}
          </div>

          {/* 手动输入路径（备用） */}
          <div>
            <label className="text-sm font-medium mb-2 block flex items-center gap-2">
              <span>或手动输入路径</span>
              <span className="text-xs text-muted-foreground">(备用)</span>
            </label>
            <Input
              placeholder="例如：D:\\Notes\\Research"
              value={vaultPathInput}
              onChange={(e) => setVaultPathInput(e.target.value)}
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-6">
          <Button
            variant="outline"
            onClick={onClose}
          >
            取消
          </Button>
          <Button onClick={onAddVault} disabled={!vaultPathInput.trim()}>
            添加
          </Button>
        </div>
      </div>
    </div>
  )
}
