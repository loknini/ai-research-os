import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ThemeMode = 'light' | 'dark' | 'system'

interface ThemeState {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
}

/**
 * 全局主题模式（浅色 / 深色 / 跟随系统）。
 * 通过 zustand persist 持久化到 localStorage（key: airos-theme），
 * 初值取系统偏好，避免首屏闪烁。
 */
export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      mode: 'system',
      setMode: (mode) => set({ mode }),
    }),
    { name: 'airos-theme' },
  ),
)

/** 将主题模式解析为是否启用暗色（system 跟随系统偏好） */
export function resolveDark(mode: ThemeMode): boolean {
  if (mode === 'light') return false
  if (mode === 'dark') return true
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** 把主题应用到 <html> 根节点（.dark 类驱动整套设计 token + 背景纵深 + .glass） */
export function applyTheme(mode: ThemeMode): void {
  document.documentElement.classList.toggle('dark', resolveDark(mode))
}
