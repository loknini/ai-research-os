/**
 * 导航配置 manifest（2026-08-19 新增）。
 *
 * 信息架构规则：一级导航只承载「业务域」；工具型能力（无独立数据模型、低频、
 * 处于工作流中间态）不进一级导航，而是作为 toolCommands 暴露给 Cmd+K 命令面板，
 * 并嵌入所属业务域（公式 → 知识库 / 引用 → 论文中心）。旧路由全部保留可直达。
 *
 * 新增能力时的判断标准：有没有独立数据模型？
 *   - 有  → 业务域，加入 navGroups
 *   - 没有 → 工具，加入 toolCommands + 嵌入所属业务域
 */
import {
  LayoutDashboard,
  FileText,
  Code2,
  BookOpen,
  MessageSquare,
  Settings,
  FunctionSquare,
  Quote,
  CheckSquare,
  History,
  Timer,
} from 'lucide-react'

export interface NavItem {
  id: string
  name: string
  icon: React.ElementType
  path: string
  description: string
  /** 命令面板匹配关键词（可选，如中文别名 / 英文名） */
  keywords?: string[]
}

export interface NavGroup {
  id: string
  label: string
  items: NavItem[]
}

/** 业务域一级导航（侧边栏渲染来源） */
export const navGroups: NavGroup[] = [
  {
    id: 'research',
    label: '研究',
    items: [
      {
        id: 'dashboard',
        name: '仪表盘',
        icon: LayoutDashboard,
        path: '/',
        description: '全局概览 · 待办聚合',
        keywords: ['home', '首页', 'overview'],
      },
      {
        id: 'chat',
        name: 'AI 助手',
        icon: MessageSquare,
        path: '/chat',
        description: '智能对话',
        keywords: ['对话', 'chat', 'assistant', '助手'],
      },
      {
        id: 'paper',
        name: '论文中心',
        icon: FileText,
        path: '/paper',
        description: '抓取管理 · 引用工具',
        keywords: ['paper', 'arxiv', '文献', '论文'],
      },
      {
        id: 'knowledge',
        name: '知识库',
        icon: BookOpen,
        path: '/knowledge',
        description: '研究笔记 · 公式工具',
        keywords: ['note', '笔记', 'obsidian', '知识'],
      },
    ],
  },
  {
    id: 'dev',
    label: '开发',
    items: [
      {
        id: 'lab',
        name: '研发实验',
        icon: Code2,
        path: '/lab',
        description: '软件开发 · 实验追踪',
        keywords: ['software', 'experiment', '项目', 'swanlab', '开发'],
      },
    ],
  },
  {
    id: 'system',
    label: '系统',
    items: [
      {
        id: 'settings',
        name: '设置',
        icon: Settings,
        path: '/settings',
        description: '配置与数据管理',
        keywords: ['config', 'llm', 'api', '配置'],
      },
    ],
  },
]

/** 工具型命令（Cmd+K 命令面板入口，不占一级导航） */
export const toolCommands: NavItem[] = [
  {
    id: 'formula',
    name: '公式识别',
    icon: FunctionSquare,
    path: '/formula',
    description: '图片 → LaTeX',
    keywords: ['latex', 'math', '数学', '识别'],
  },
  {
    id: 'citation',
    name: '引用生成',
    icon: Quote,
    path: '/citation',
    description: '检索 → 引用格式',
    keywords: ['bibtex', 'reference', '参考文献', '引用'],
  },
  {
    id: 'task',
    name: '任务清单',
    icon: CheckSquare,
    path: '/task',
    description: '待办事项',
    keywords: ['todo', '待办', '任务'],
  },
  {
    id: 'agent-runs',
    name: '运行历史',
    icon: History,
    path: '/agent-runs',
    description: '后台 Agent 运行记录',
    keywords: ['run', 'history', '后台', '记录'],
  },
  {
    id: 'cron',
    name: '定时任务',
    icon: Timer,
    path: '/cron',
    description: '定时触发 Agent 与论文抓取',
    keywords: ['cron', 'schedule', '定时', '自动化'],
  },
]

/** 全部命令（导航 + 工具），供命令面板统一检索 */
export const allCommands: NavItem[] = [
  ...navGroups.flatMap((group) => group.items),
  ...toolCommands,
]

/** 命令分组（命令面板展示用）：导航业务域 + 工具组 */
export const commandGroups: { id: string; label: string; items: NavItem[] }[] = [
  ...navGroups.map((group) => ({ id: group.id, label: group.label, items: group.items })),
  { id: 'tools', label: '工具', items: toolCommands },
]
