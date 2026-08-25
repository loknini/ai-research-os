import { useMemo } from 'react'
import type { SoftwareProject, ProjectStatus } from '@/types'

/** 项目统计数据 */
export interface SoftwareStats {
  total: number
  byStatus: {
    design: number
    developing: number
    testing: number
    deployed: number
  }
}

/**
 * 派生数据 Hook：统计 + 筛选项目
 * 对应原容器内 103–111 行的 stats useMemo 与 114–120 行的 filteredProjects useMemo。
 */
export function useSoftwareData(
  projects: SoftwareProject[],
  filterStatus: ProjectStatus | 'all',
  searchQuery: string
): { stats: SoftwareStats; filteredProjects: SoftwareProject[] } {
  const stats = useMemo<SoftwareStats>(
    () => ({
      total: projects.length,
      byStatus: {
        design: projects.filter((p) => p.status === 'design').length,
        developing: projects.filter((p) => p.status === 'developing').length,
        testing: projects.filter((p) => p.status === 'testing').length,
        deployed: projects.filter((p) => p.status === 'deployed').length
      }
    }),
    [projects]
  )

  const filteredProjects = useMemo<SoftwareProject[]>(() => {
    return projects.filter((project) => {
      if (filterStatus !== 'all' && project.status !== filterStatus) return false
      if (searchQuery && !project.name.toLowerCase().includes(searchQuery.toLowerCase())) return false
      return true
    })
  }, [projects, filterStatus, searchQuery])

  return { stats, filteredProjects }
}
