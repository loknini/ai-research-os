import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { AlertTriangle, X } from 'lucide-react'

interface ConfirmDialogProps {
  isOpen: boolean
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
  variant?: 'danger' | 'warning' | 'info'
  onConfirm: () => void
  onCancel?: () => void
  onClose?: () => void
}

export function ConfirmDialog({
  isOpen,
  title = '确认操作',
  message,
  confirmText = '确认',
  cancelText = '取消',
  variant = 'danger',
  onConfirm,
  onCancel,
  onClose,
}: ConfirmDialogProps) {
  // 兼容 onClose 和 onCancel
  const handleCancel = onCancel || onClose || (() => {})
  const [isVisible, setIsVisible] = useState(false)

  useEffect(() => {
    if (isOpen) {
      setIsVisible(true)
    } else {
      const timer = setTimeout(() => setIsVisible(false), 200)
      return () => clearTimeout(timer)
    }
  }, [isOpen])

  if (!isVisible) return null

  const variantStyles = {
    danger: {
      icon: <AlertTriangle className="w-12 h-12 text-red-500" />,
      confirmButton: 'bg-red-500 hover:bg-red-600 text-white',
      border: 'border-red-200',
      bg: 'bg-red-50',
    },
    warning: {
      icon: <AlertTriangle className="w-12 h-12 text-yellow-500" />,
      confirmButton: 'bg-yellow-500 hover:bg-yellow-600 text-white',
      border: 'border-yellow-200',
      bg: 'bg-yellow-50',
    },
    info: {
      icon: <AlertTriangle className="w-12 h-12 text-blue-500" />,
      confirmButton: 'bg-blue-500 hover:bg-blue-600 text-white',
      border: 'border-blue-200',
      bg: 'bg-blue-50',
    },
  }

  const styles = variantStyles[variant]

  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center p-4 transition-opacity duration-200 ${
        isOpen ? 'opacity-100' : 'opacity-0'
      }`}
    >
      {/* 背景遮罩 */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={handleCancel}
      />

      {/* 对话框 */}
      <div
        className={`relative w-full max-w-md transform transition-all duration-200 ${
          isOpen ? 'scale-100 translate-y-0' : 'scale-95 translate-y-4'
        }`}
      >
        <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl border overflow-hidden">
          {/* 头部 */}
          <div className={`px-6 py-4 border-b ${styles.border} ${styles.bg}`}>
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold">{title}</h3>
              <button
                onClick={handleCancel}
                className="p-1 rounded-full hover:bg-black/10 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* 内容 */}
          <div className="px-6 py-6">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0">{styles.icon}</div>
              <div className="flex-1">
                <p className="text-gray-600 dark:text-gray-300 leading-relaxed">
                  {message}
                </p>
              </div>
            </div>
          </div>

          {/* 按钮 */}
          <div className="px-6 py-4 bg-gray-50 dark:bg-gray-800/50 flex justify-end gap-3">
            <Button variant="outline" onClick={handleCancel}>
              {cancelText}
            </Button>
            <Button className={styles.confirmButton} onClick={onConfirm}>
              {confirmText}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

// Hook 方便使用
export function useConfirmDialog() {
  const [isOpen, setIsOpen] = useState(false)
  const [config, setConfig] = useState<{
    title?: string
    message: string
    onConfirm: () => void
    variant?: 'danger' | 'warning' | 'info'
  }>({ message: '', onConfirm: () => {} })

  const showConfirm = (options: {
    title?: string
    message: string
    onConfirm: () => void
    variant?: 'danger' | 'warning' | 'info'
  }) => {
    setConfig(options)
    setIsOpen(true)
  }

  const hideConfirm = () => {
    setIsOpen(false)
  }

  const ConfirmDialogComponent = () => (
    <ConfirmDialog
      isOpen={isOpen}
      title={config.title}
      message={config.message}
      variant={config.variant || 'danger'}
      onConfirm={() => {
        config.onConfirm()
        hideConfirm()
      }}
      onCancel={hideConfirm}
    />
  )

  return { showConfirm, hideConfirm, ConfirmDialogComponent }
}
