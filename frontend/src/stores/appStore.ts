import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'
import type { AppState, Paper, Experiment, SoftwareProject, Task, Skill } from '@/types'

interface AppActions {
  // 连接管理（后端健康检测）
  setConnected: (connected: boolean) => void
  setConnecting: (connecting: boolean) => void
  setConnectionError: (error: string | undefined) => void

  // Hub 管理
  setCurrentHub: (hub: string) => void

  // 侧边栏状态
  toggleSidebar: () => void
  setSidebarCollapsed: (collapsed: boolean) => void
  setSidebarWidth: (width: number) => void

  // 空间隔离（space-key 软隔离）
  setSpace: (key: string) => void
  clearSpace: () => void

  // 当前聊天会话持久化
  setChatConversationId: (id: string | null) => void

  // 数据管理
  setPapers: (papers: Paper[]) => void
  addPaper: (paper: Paper) => void
  updatePaper: (id: string, updates: Partial<Paper>) => void
  deletePaper: (id: string) => void
  
  setExperiments: (experiments: Experiment[]) => void
  addExperiment: (experiment: Experiment) => void
  updateExperiment: (id: string, updates: Partial<Experiment>) => void
  
  setProjects: (projects: SoftwareProject[]) => void
  addProject: (project: SoftwareProject) => void
  
  setTasks: (tasks: Task[]) => void
  addTask: (task: Task) => void
  updateTask: (id: string, updates: Partial<Task>) => void
  
  setSkills: (skills: Skill[]) => void
  
  // 加载状态
  setLoadingPapers: (loading: boolean) => void
  setLoadingExperiments: (loading: boolean) => void
}

const initialState: Omit<AppState, keyof AppActions> = {
  isConnected: false,
  isConnecting: false,
  connectionError: undefined,

  currentHub: 'dashboard',

  sidebarCollapsed: false,
  sidebarWidth: 256,

  spaceKey: '',

  chatConversationId: null,

  papers: [],
  experiments: [],
  projects: [],
  tasks: [],
  skills: [],
  
  isLoadingPapers: false,
  isLoadingExperiments: false,
}

export const useAppStore = create<AppState & AppActions>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,
        
        // 连接管理
        setConnected: (connected) => set({ isConnected: connected }),
        setConnecting: (connecting) => set({ isConnecting: connecting }),
        setConnectionError: (error) => set({ connectionError: error }),
        

        // Hub 管理
        setCurrentHub: (hub) => set({ currentHub: hub }),

        // 侧边栏状态
        toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
        setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
        setSidebarWidth: (width) => set({ sidebarWidth: Math.min(Math.max(width, 180), 360) }),

        // 空间隔离（space-key 软隔离）
        setSpace: (key) => set({ spaceKey: key }),
        clearSpace: () => set({ spaceKey: '' }),

        // 当前聊天会话持久化
        setChatConversationId: (id) => set({ chatConversationId: id }),

        // 论文管理
        setPapers: (papers) => set({ papers }),
        addPaper: (paper) => set((state) => ({ papers: [...state.papers, paper] })),
        updatePaper: (id, updates) => set((state) => ({
          papers: state.papers.map((p) => (p.id === id ? { ...p, ...updates } : p)),
        })),
        deletePaper: (id) => set((state) => ({
          papers: state.papers.filter((p) => p.id !== id),
        })),
        
        // 实验管理
        setExperiments: (experiments) => set({ experiments }),
        addExperiment: (experiment) => set((state) => ({
          experiments: [...state.experiments, experiment],
        })),
        updateExperiment: (id, updates) => set((state) => ({
          experiments: state.experiments.map((e) => (e.id === id ? { ...e, ...updates } : e)),
        })),
        
        // 项目管理
        setProjects: (projects) => set({ projects }),
        addProject: (project) => set((state) => ({
          projects: [...state.projects, project],
        })),
        
        // 任务管理
        setTasks: (tasks) => set({ tasks }),
        addTask: (task) => set((state) => ({ tasks: [...state.tasks, task] })),
        updateTask: (id, updates) => set((state) => ({
          tasks: state.tasks.map((t) => (t.id === id ? { ...t, ...updates } : t)),
        })),
        
        // Skills
        setSkills: (skills) => set({ skills }),
        
        // 加载状态
        setLoadingPapers: (loading) => set({ isLoadingPapers: loading }),
        setLoadingExperiments: (loading) => set({ isLoadingExperiments: loading }),
      }),
      {
        name: 'ai-research-os-storage',
        partialize: (state) => ({
          currentHub: state.currentHub,
          spaceKey: state.spaceKey,
          sidebarCollapsed: state.sidebarCollapsed,
          sidebarWidth: state.sidebarWidth,
          chatConversationId: state.chatConversationId,
        }),
      }
    ),
    { name: 'AppStore' }
  )
)
