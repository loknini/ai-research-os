/** DAG 节点 id → 中文名回落映射（内置团队真名，避免“用户”占位误显）。 */
export const DAG_NAME_MAP: Record<string, string> = {
  method: '方法分析师',
  evidence: '证据审查员',
  novelty: '创新性分析师',
  editor: '综述编辑',
  organizer: '资料整理员',
  connector: '关联分析师',
  critic: '批判性审查员',
  architect: '架构师',
  risk: '风险分析师',
  planner: '规划师',
  reviewer: '评审者',
  integrator: '项目方案整合者',
  'dev-analysis': '需求与代码分析师',
  'dev-implementation': '实现工程师',
  'dev-testing': '测试工程师',
  'dev-review': '代码审查员',
}

export function resolveAgentName(
  id: string | undefined,
  nodesMap?: Record<string, string>,
): string {
  if (!id) return '系统'
  if (nodesMap?.[id] && nodesMap[id] !== '用户') return nodesMap[id]
  if (DAG_NAME_MAP[id] && DAG_NAME_MAP[id] !== '用户') return DAG_NAME_MAP[id]
  if (id === 'user') return '用户'
  // 未知 phase / node：直接返回 id，避免误标“用户”
  return id
}
