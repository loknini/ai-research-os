import { useState, useEffect, useCallback } from 'react'
import { Button } from './button'
import { Badge } from './badge'
import { ScrollArea } from './scroll-area'
import { toast } from './toast'
import { cn } from '@/utils'
import {
  History,
  RotateCcw,
  GitCompare,
  X,
  ChevronDown,
  ChevronUp,
  Clock,
  User
} from 'lucide-react'

interface Version {
  id: string
  entityType: string
  entityId: string
  versionNumber: number
  data: any
  changeSummary: string
  createdBy: string
  createdAt: number
}

interface VersionHistoryProps {
  entityType: 'note' | 'task' | 'project'
  entityId: string
  isOpen: boolean
  onClose: () => void
  onRestore?: (data: any) => void
}

export function VersionHistory({
  entityType,
  entityId,
  isOpen,
  onClose,
  onRestore
}: VersionHistoryProps) {
  const [versions, setVersions] = useState<Version[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [selectedVersions, setSelectedVersions] = useState<string[]>([])
  const [expandedVersions, setExpandedVersions] = useState<Set<string>>(new Set())
  const [compareResult, setCompareResult] = useState<any>(null)
  const [restoringVersion, setRestoringVersion] = useState<string | null>(null)

  const loadVersions = useCallback(async () => {
    if (!entityId) return
    
    setIsLoading(true)
    try {
      const response = await fetch(`/api/versions/${entityType}/${entityId}`)
      if (response.ok) {
        const data = await response.json()
        if (data.success) {
          setVersions(data.versions || [])
        }
      }
    } catch (error) {
      console.error('Failed to load versions:', error)
      toast({ title: '加载版本历史失败', variant: 'error' })
    } finally {
      setIsLoading(false)
    }
  }, [entityType, entityId])

  useEffect(() => {
    if (isOpen) {
      loadVersions()
    }
  }, [isOpen, loadVersions])

  const toggleVersionSelection = (versionId: string) => {
    setSelectedVersions(prev => {
      if (prev.includes(versionId)) {
        return prev.filter(id => id !== versionId)
      }
      if (prev.length >= 2) {
        return [prev[1], versionId]
      }
      return [...prev, versionId]
    })
  }

  const toggleExpand = (versionId: string) => {
    setExpandedVersions(prev => {
      const newSet = new Set(prev)
      if (newSet.has(versionId)) {
        newSet.delete(versionId)
      } else {
        newSet.add(versionId)
      }
      return newSet
    })
  }

  const handleCompare = async () => {
    if (selectedVersions.length !== 2) {
      toast({ title: '请选择两个版本进行对比', variant: 'error' })
      return
    }

    try {
      const response = await fetch('/api/versions/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          versionId1: selectedVersions[0],
          versionId2: selectedVersions[1]
        })
      })

      if (response.ok) {
        const data = await response.json()
        if (data.success) {
          setCompareResult(data.comparison)
        }
      }
    } catch (error) {
      console.error('Compare error:', error)
      toast({ title: '对比失败', variant: 'error' })
    }
  }

  const handleRestore = async (versionId: string) => {
    setRestoringVersion(versionId)
    try {
      const response = await fetch('/api/versions/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ versionId })
      })

      if (response.ok) {
        const data = await response.json()
        if (data.success) {
          toast({ title: '版本恢复成功', variant: 'success' })
          onRestore?.(data.data)
          loadVersions()
        } else {
          toast({ title: data.error || '恢复失败', variant: 'error' })
        }
      }
    } catch (error) {
      console.error('Restore error:', error)
      toast({ title: '恢复失败', variant: 'error' })
    } finally {
      setRestoringVersion(null)
    }
  }

  const formatDate = (timestamp: number) => {
    return new Date(timestamp * 1000).toLocaleString('zh-CN')
  }

  const renderDiff = (diff: any) => {
    if (!diff) return null

    return (
      <div className="space-y-2 mt-2">
        {Object.entries(diff.added || {}).length > 0 && (
          <div className="bg-green-50 p-2 rounded">
            <p className="text-xs font-medium text-green-700 mb-1">新增:</p>
            {Object.entries(diff.added).map(([key, value]) => (
              <p key={key} className="text-xs text-green-600">
                + {key}: {JSON.stringify(value)}
              </p>
            ))}
          </div>
        )}
        {Object.entries(diff.removed || {}).length > 0 && (
          <div className="bg-red-50 p-2 rounded">
            <p className="text-xs font-medium text-red-700 mb-1">删除:</p>
            {Object.entries(diff.removed).map(([key, value]) => (
              <p key={key} className="text-xs text-red-600">
                - {key}: {JSON.stringify(value)}
              </p>
            ))}
          </div>
        )}
        {Object.entries(diff.modified || {}).length > 0 && (
          <div className="bg-yellow-50 p-2 rounded">
            <p className="text-xs font-medium text-yellow-700 mb-1">修改:</p>
            {Object.entries(diff.modified).map(([key, value]: [string, any]) => (
              <div key={key} className="text-xs">
                <p className="text-red-600">- {key}: {JSON.stringify(value.old)}</p>
                <p className="text-green-600">+ {key}: {JSON.stringify(value.new)}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="w-full max-w-3xl h-[80vh] bg-card rounded-lg shadow-xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b">
          <div className="flex items-center gap-2">
            <History className="w-5 h-5" />
            <h2 className="font-semibold">版本历史</h2>
            <Badge variant="secondary">{versions.length} 个版本</Badge>
          </div>
          <div className="flex items-center gap-2">
            {selectedVersions.length === 2 && (
              <Button variant="outline" size="sm" onClick={handleCompare}>
                <GitCompare className="w-4 h-4 mr-1" />
                对比
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={onClose}>
              <X className="w-4 h-4" />
            </Button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden flex">
          {/* Version List */}
          <ScrollArea className="flex-1 p-4">
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
              </div>
            ) : versions.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <History className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>暂无版本历史</p>
              </div>
            ) : (
              <div className="space-y-2">
                {versions.map((version) => (
                  <div
                    key={version.id}
                    className={cn(
                      'border rounded-lg p-3 transition-colors',
                      selectedVersions.includes(version.id)
                        ? 'border-primary bg-primary/5'
                        : 'hover:bg-muted/50'
                    )}
                  >
                    <div className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        checked={selectedVersions.includes(version.id)}
                        onChange={() => toggleVersionSelection(version.id)}
                        className="mt-1"
                      />
                      <div className="flex-1">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="font-medium">
                              版本 #{version.versionNumber}
                            </span>
                            <Badge variant="outline" className="text-xs">
                              <Clock className="w-3 h-3 mr-1" />
                              {formatDate(version.createdAt)}
                            </Badge>
                          </div>
                          <div className="flex items-center gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => toggleExpand(version.id)}
                            >
                              {expandedVersions.has(version.id) ? (
                                <ChevronUp className="w-4 h-4" />
                              ) : (
                                <ChevronDown className="w-4 h-4" />
                              )}
                            </Button>
                          </div>
                        </div>

                        <div className="flex items-center gap-2 mt-1 text-sm text-muted-foreground">
                          <User className="w-3 h-3" />
                          <span>{version.createdBy || '用户'}</span>
                          {version.changeSummary && (
                            <>
                              <span>•</span>
                              <span>{version.changeSummary}</span>
                            </>
                          )}
                        </div>

                        {/* Actions */}
                        <div className="flex gap-2 mt-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleRestore(version.id)}
                            disabled={restoringVersion === version.id}
                          >
                            {restoringVersion === version.id ? (
                              <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-primary mr-1" />
                            ) : (
                              <RotateCcw className="w-3 h-3 mr-1" />
                            )}
                            恢复
                          </Button>
                        </div>

                        {/* Expanded Content */}
                        {expandedVersions.has(version.id) && (
                          <div className="mt-3 p-3 bg-muted rounded-lg">
                            <p className="text-xs font-medium mb-2">数据快照:</p>
                            <pre className="text-xs overflow-auto max-h-48">
                              {JSON.stringify(version.data, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>

          {/* Compare Panel */}
          {compareResult && (
            <div className="w-80 border-l bg-muted/30 p-4 overflow-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-medium">版本对比</h3>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setCompareResult(null)}
                >
                  <X className="w-4 h-4" />
                </Button>
              </div>
              {renderDiff(compareResult.diff)}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
