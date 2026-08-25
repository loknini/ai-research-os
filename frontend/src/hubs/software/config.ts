import type { ProjectStatus } from '@/types'
import { Code2, Lightbulb, CheckCircle2, Rocket, Folder } from 'lucide-react'

/** 项目状态配置：标签、颜色、图标 */
export const STATUS_CONFIG: Record<
  ProjectStatus,
  { label: string; color: string; icon: typeof Code2 }
> = {
  design: { label: '设计阶段', color: 'bg-purple-500', icon: Lightbulb },
  developing: { label: '开发中', color: 'bg-blue-500', icon: Code2 },
  testing: { label: '测试中', color: 'bg-yellow-500', icon: CheckCircle2 },
  deployed: { label: '已部署', color: 'bg-green-500', icon: Rocket },
  archived: { label: '已归档', color: 'bg-gray-400', icon: Folder }
}

/** 可选技术栈列表 */
export const TECH_STACK_OPTIONS = [
  'React', 'Vue', 'Angular', 'Svelte',
  'TypeScript', 'JavaScript', 'Python', 'Go', 'Rust', 'Java',
  'Node.js', 'Deno', 'Bun',
  'TailwindCSS', 'Styled Components', 'Sass',
  'PostgreSQL', 'MongoDB', 'MySQL', 'SQLite', 'Redis',
  'Docker', 'Kubernetes', 'AWS', 'Vercel', 'Netlify',
  'Express', 'Fastify', 'NestJS', 'FastAPI', 'Django', 'Flask'
]
