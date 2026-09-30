import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

// Tailwind 类名合并
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// 格式化日期
export function formatDate(timestamp: number | string, options?: Intl.DateTimeFormatOptions): string {
  const date = typeof timestamp === 'string' ? new Date(timestamp) : new Date(timestamp)
  const defaultOptions: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    ...options,
  }
  return date.toLocaleDateString('zh-CN', defaultOptions)
}

// 格式化相对时间
export function formatRelativeTime(timestamp: number): string {
  const now = Date.now()
  const diff = now - timestamp
  
  const seconds = Math.floor(diff / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  
  if (days > 0) return `${days} 天前`
  if (hours > 0) return `${hours} 小时前`
  if (minutes > 0) return `${minutes} 分钟前`
  return '刚刚'
}

// 截断文本
export function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength) + '...'
}

// 生成唯一 ID
export function generateId(): string {
  return Math.random().toString(36).substring(2, 15)
}

// 深拷贝
export function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj))
}

// 防抖
export function debounce<T extends (...args: unknown[]) => unknown>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: ReturnType<typeof setTimeout> | null = null
  return (...args: Parameters<T>) => {
    if (timeout) clearTimeout(timeout)
    timeout = setTimeout(() => func(...args), wait)
  }
}

// 节流
export function throttle<T extends (...args: unknown[]) => unknown>(
  func: T,
  limit: number
): (...args: Parameters<T>) => void {
  let inThrottle = false
  return (...args: Parameters<T>) => {
    if (!inThrottle) {
      func(...args)
      inThrottle = true
      setTimeout(() => (inThrottle = false), limit)
    }
  }
}

// 存储本地数据
export function saveToLocalStorage<T>(key: string, data: T): void {
  try {
    localStorage.setItem(key, JSON.stringify(data))
  } catch (error) {
    console.error('Failed to save to localStorage:', error)
  }
}

// 读取本地数据
export function loadFromLocalStorage<T>(key: string, defaultValue: T): T {
  try {
    const item = localStorage.getItem(key)
    return item ? (JSON.parse(item) as T) : defaultValue
  } catch (error) {
    console.error('Failed to load from localStorage:', error)
    return defaultValue
  }
}

// 下载文件
export function downloadFile(content: string, filename: string, contentType: string = 'text/plain'): void {
  const blob = new Blob([content], { type: contentType })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

// 文件大小格式化
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

// 验证 arXiv ID
export function isValidArxivId(id: string): boolean {
  const arxivPattern = /^\d{4}\.\d{4,5}$/
  return arxivPattern.test(id)
}

// 提取 arXiv ID 从 URL
export function extractArxivId(url: string): string | null {
  const match = url.match(/arxiv\.org\/abs\/(\d{4}\.\d{4,5})/)
  return match ? match[1] : null
}

// 清除模型误作为普通文本输出的工具协议。该内容既不展示，也不保留调试副本；
// 未闭合的 <tool_call> 尾部同样丢弃，避免流式生成过程中短暂裸露内部标记。
export function stripToolCallTrace(content: string): string {
  if (!content) return content
  return content
    .replace(/<tool_call\b[^>]*>[\s\S]*?(?:<\/tool_call\s*>|$)/gi, '')
    .replace(/<function(?:\b|=)[^>]*>[\s\S]*?(?:<\/function\s*>|$)/gi, '')
    .replace(/<\/?(?:tool_call\b|function(?:\b|=)|parameter(?:\b|=))[^>]*>/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
