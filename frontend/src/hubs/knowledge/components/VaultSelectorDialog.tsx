// VaultSelectorDialog component for the Knowledge Hub.
// Extracted from the original monolithic index.tsx add-Vault dialog (lines 812-907).
// Controlled presentational component: the container owns all state and passes the
// setters + handlers down; server filesystem browsing is isolated in
// ServerDirectoryPicker so manual absolute-path entry remains available.

import { Dispatch, SetStateAction } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { FolderOpen } from 'lucide-react'
import { ServerDirectoryPicker } from './ServerDirectoryPicker'

interface VaultSelectorDialogProps {
  vaultNameInput: string
  vaultPathInput: string
  setVaultNameInput: Dispatch<SetStateAction<string>>
  setVaultPathInput: Dispatch<SetStateAction<string>>
  onSelectDirectory: (path: string, name: string) => void
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
      <div className="bg-background rounded-lg p-6 w-[720px] max-w-[94vw] max-h-[90vh] overflow-y-auto">
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

          <div>
            <label className="text-sm font-medium mb-2 flex items-center gap-2">
              <FolderOpen className="h-4 w-4" />选择服务端目录
            </label>
            <ServerDirectoryPicker selectedPath={vaultPathInput} onSelect={onSelectDirectory} />
          </div>

          {/* 手动输入路径（备用） */}
          <div>
            <label className="text-sm font-medium mb-2 block flex items-center gap-2">
              <span>或手动输入服务端绝对路径</span>
              <span className="text-xs text-muted-foreground">（保留方式）</span>
            </label>
            <Input
              placeholder="例如：D:\\Notes\\Research"
              value={vaultPathInput}
              onChange={(e) => setVaultPathInput(e.target.value)}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              路径必须位于运行后端的电脑上，例如 D:\Notes\Research。
            </p>
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
