import { useCallback, useEffect, useState } from 'react'
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react'
import { cn } from '@/utils'

interface ToastProps {
  message: string
  type?: 'success' | 'error' | 'info'
  description?: string
  action?: { label: string; onClick: () => void }
  onClose: () => void
  duration?: number
}

// 全局 toast 状态管理
let toastListeners: Array<(toasts: ToastItem[]) => void> = []
let toasts: ToastItem[] = []

interface ToastItem {
  id: string
  title?: string
  message: string
  type: 'success' | 'error' | 'info'
  description?: string
  action?: { label: string; onClick: () => void }
}

const notifyListeners = () => {
  toastListeners.forEach(listener => listener([...toasts]))
}

const addToast = (item: Omit<ToastItem, 'id'>) => {
  const id = Date.now().toString() + Math.random().toString(36).substr(2, 9)
  const newToast = { ...item, id }
  toasts = [...toasts, newToast]
  notifyListeners()
  
  // Auto remove after 3 seconds
  setTimeout(() => {
    removeToast(id)
  }, 3000)
}

const removeToast = (id: string) => {
  toasts = toasts.filter(t => t.id !== id)
  notifyListeners()
}

// 全局 toast 函数
export const toast = ({ title, description, variant = 'info', action }: { 
  title?: string 
  description?: string 
  variant?: 'success' | 'error' | 'info'
  action?: { label: string; onClick: () => void }
}) => {
  addToast({
    title,
    message: title || description || '',
    description,
    type: variant,
    action
  })
}

// 全局 Toast 容器组件
export function GlobalToastContainer() {
  const [localToasts, setLocalToasts] = useState<ToastItem[]>([])

  useEffect(() => {
    const listener = (newToasts: ToastItem[]) => {
      setLocalToasts(newToasts)
    }
    toastListeners.push(listener)
    return () => {
      toastListeners = toastListeners.filter(l => l !== listener)
    }
  }, [])

  return (
    <>
      {localToasts.map(toast => (
        <Toast
          key={toast.id}
          message={toast.message}
          type={toast.type}
          description={toast.description}
          action={toast.action}
          onClose={() => removeToast(toast.id)}
        />
      ))}
    </>
  )
}

export function Toast({ message, type = 'info', description, action, onClose, duration = 3000 }: ToastProps) {
  const [isVisible, setIsVisible] = useState(false)

  useEffect(() => {
    // 入场动画
    requestAnimationFrame(() => setIsVisible(true))

    // 自动关闭
    const timer = setTimeout(() => {
      setIsVisible(false)
      setTimeout(onClose, 300)
    }, duration)

    return () => clearTimeout(timer)
  }, [duration, onClose])

  const icons = {
    success: <CheckCircle className="w-5 h-5 text-green-500" />,
    error: <AlertCircle className="w-5 h-5 text-red-500" />,
    info: <Info className="w-5 h-5 text-blue-500" />
  }

  const bgColors = {
    success: 'bg-green-50 border-green-200',
    error: 'bg-red-50 border-red-200',
    info: 'bg-blue-50 border-blue-200'
  }

  return (
    <div
      className={cn(
        'fixed top-4 right-4 z-50 flex items-center gap-3 px-4 py-3 rounded-lg border shadow-lg transition-all duration-300 max-w-sm',
        bgColors[type],
        isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-4'
      )}
    >
      {icons[type]}
      <div className="min-w-0">
        <span className="text-sm font-medium block">{message}</span>
        {description && (
          <span className="text-xs text-muted-foreground block mt-0.5 break-words">{description}</span>
        )}
      </div>
      {action && (
        <button
          onClick={() => {
            action.onClick()
            setIsVisible(false)
            setTimeout(onClose, 300)
          }}
          className="ml-1 px-2 py-1 text-xs font-medium rounded-md hover:bg-black/5 whitespace-nowrap"
        >
          {action.label}
        </button>
      )}
      <button
        onClick={() => {
          setIsVisible(false)
          setTimeout(onClose, 300)
        }}
        className="ml-2 p-1 hover:bg-black/5 rounded"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}

// Toast 容器 Hook
export function useToast() {
  const [toasts, setToasts] = useState<Array<{ id: string; message: string; type: 'success' | 'error' | 'info' }>>([])

  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'info') => {
    const id = Date.now().toString()
    setToasts(prev => [...prev, { id, message, type }])
  }, [])

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const ToastContainer = () => (
    <>
      {toasts.map(toast => (
        <Toast
          key={toast.id}
          message={toast.message}
          type={toast.type}
          onClose={() => removeToast(toast.id)}
        />
      ))}
    </>
  )

  return { showToast, ToastContainer }
}
