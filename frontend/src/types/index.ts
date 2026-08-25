// 论文类型

export interface Paper {
  id: string
  title: string
  authors: string[]
  abstract: string
  arxivId: string
  pdfUrl: string
  categories: string[]
  publishedDate: string
  localPath?: string
  summary?: string
  bibtex?: string
  tags: string[]
  isRead: boolean
  isFavorite: boolean
  addedAt: number
}

export interface PaperMetadata {
  papers: Paper[]
  lastUpdated: string
}

// 实验类型

// 软件项目类型（增强版）

export type ProjectStatus = 'design' | 'developing' | 'testing' | 'deployed' | 'archived'

export interface SoftwareProject {
  id: string
  name: string
  description?: string
  ideaDescription?: string  // 原始想法描述
  techStack: string[]
  status: ProjectStatus
  localPath?: string
  githubUrl?: string
  architecture?: ProjectArchitecture
  features: ProjectFeature[]
  milestones: ProjectMilestone[]
  aiGeneratedCode: boolean
  createdAt: number
  updatedAt: number
}

export interface ProjectArchitecture {
  pattern?: string  // e.g., 'mvc', 'microservices', 'layered'
  components?: ArchitectureComponent[]
  techChoices?: TechChoice[]
  diagram?: string  // Mermaid or ASCII diagram
}

export interface ArchitectureComponent {
  name: string
  description: string
  techStack: string[]
  responsibilities: string[]
}

export interface TechChoice {
  category: string  // e.g., 'frontend', 'backend', 'database'
  choice: string
  reason: string
  alternatives?: string[]
}

export interface ProjectFeature {
  id: string
  name: string
  description: string
  status: 'todo' | 'in_progress' | 'done'
  priority: 'low' | 'medium' | 'high'
}

export interface ProjectMilestone {
  id: string
  name: string
  description: string
  targetDate?: string
  completedAt?: number
  status: 'pending' | 'in_progress' | 'completed'
}

// Skill 类型

export interface Skill {
  name: string
  description: string
  emoji?: string
  skillKey: string
  metadata?: {
    os?: string[]
    requires?: {
      bins?: string[]
      env?: string[]
    }
  }
}

// 任务类型（增强版）

export type TaskStatus = 'todo' | 'in_progress' | 'done' | 'archived'
export type TaskPriority = 'low' | 'medium' | 'high' | 'urgent'

export interface Task {
  id: string
  title: string
  description?: string
  status: TaskStatus
  priority: TaskPriority
  deadline?: number  // 时间戳
  tags: string[]
  projectId?: string  // 关联的项目ID
  parentTaskId?: string  // 父任务ID（支持子任务）
  subTasks?: Task[]  // 子任务（前端计算）
  aiSuggested: boolean  // 是否 AI 建议的任务
  completedAt?: number
  createdAt: number
  updatedAt: number
}

export interface TaskFilter {
  status?: TaskStatus[]
  priority?: TaskPriority[]
  projectId?: string
  tags?: string[]
  searchQuery?: string
}

export interface TaskStats {
  total: number
  todo: number
  inProgress: number
  done: number
  byPriority: Record<TaskPriority, number>
  overdue: number
}

// 笔记类型

export type NoteType = 'note' | 'idea' | 'summary' | 'code_snippet'

export interface Note {
  id: string
  title: string
  content: string
  summary?: string
  type: NoteType
  tags: string[]
  paperId?: string
  projectId?: string
  parentNoteId?: string
  links?: string[]  // 链接的笔记ID
  isFavorite: boolean
  aiGenerated: boolean
  createdAt: number
  updatedAt: number
}

// 实验类型

export type ExperimentStatus = 'planning' | 'running' | 'completed' | 'failed'

export interface Experiment {
  id: string
  name: string
  description?: string
  projectId?: string
  status: ExperimentStatus
  config: Record<string, unknown>
  tags: string[]
  swanlabProject?: string
  swanlabExperimentId?: string
  totalRuns: number
  bestMetricName?: string
  bestMetricValue?: number
  runs?: ExperimentRun[]
  createdAt: number
  updatedAt: number
}

export type ExperimentRunStatus = 'running' | 'completed' | 'failed' | 'aborted'

export interface ExperimentRun {
  id: string
  experimentId: string
  runNumber: number
  status: ExperimentRunStatus
  config: Record<string, unknown>
  metrics: Record<string, number>
  swanlabRunId?: string
  startedAt: number
  endedAt?: number
  duration?: number
}

// 应用状态

export interface AppState {
  // 连接状态（后端健康检测）
  isConnected: boolean
  isConnecting: boolean
  connectionError?: string
  
  // 当前 Hub
  currentHub: string

  // 侧边栏状态
  sidebarCollapsed: boolean
  sidebarWidth: number

  // 空间隔离（space-key 软隔离）：当前选中的空间口令（归一前原始值）
  // 为空表示尚未选择空间；归一（trim + lower）后作为 space_id 透传给后端。
  spaceKey: string

  // 当前选中的聊天会话 ID（跨 Hub 切换时持久化，切回 Chat 后自动恢复）
  chatConversationId: string | null

  // 数据
  papers: Paper[]
  experiments: Experiment[]
  projects: SoftwareProject[]
  tasks: Task[]
  skills: Skill[]
  
  // 加载状态
  isLoadingPapers: boolean
  isLoadingExperiments: boolean
}

// Hub 配置

export interface HubConfig {
  id: string
  name: string
  icon: string
  path: string
  description: string
  enabled: boolean
}

// 消息类型

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  metadata?: {
    skillName?: string
    toolCalls?: string[]
    result?: any
  }
}

// Cron 定时任务类型

export interface CronJob {
  id: string
  name: string
  description: string
  schedule: string  // cron expression or 'daily', 'weekly', etc.
  command: string   // the command to execute (job_type=command 时)
  jobType: 'command' | 'agent_run' | 'arxiv_fetch'
  payload: Record<string, any> | null
  enabled: boolean
  lastRun?: number
  nextRun?: number
  runCount: number
  createdAt: number
}

export interface CronRunHistory {
  id: string
  cron_job_id: string
  spaceId: string
  status: 'success' | 'failed' | 'timeout' | 'error'
  output: string
  startedAt: number
  finishedAt: number
  durationMs: number
}
