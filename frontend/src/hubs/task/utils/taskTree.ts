import type { Task } from '@/types'

/**
 * 依据 parentTaskId 将扁平任务列表构建为树形结构。
 * 返回根任务数组，每个根任务的 subTasks 包含其直接子任务。
 */
export function buildTaskTree(tasks: Task[]): Task[] {
  const taskMap = new Map<string, Task & { subTasks: Task[] }>(
    tasks.map((t: Task) => [t.id, { ...t, subTasks: [] }])
  )
  const rootTasks: Task[] = []

  taskMap.forEach((task) => {
    if (task.parentTaskId && taskMap.has(task.parentTaskId)) {
      const parent = taskMap.get(task.parentTaskId)!
      parent.subTasks = parent.subTasks || []
      parent.subTasks.push(task)
    } else {
      rootTasks.push(task)
    }
  })

  return rootTasks
}

/**
 * 递归展平任务树为单层数组（供统计使用）。
 */
export function flattenTasks(taskList: Task[]): Task[] {
  const result: Task[] = []
  taskList.forEach((task) => {
    result.push(task)
    if (task.subTasks) {
      result.push(...flattenTasks(task.subTasks))
    }
  })
  return result
}

/**
 * 递归过滤任务树：仅保留满足 predicate 的节点，
 * 并对保留节点的子任务继续递归过滤（子节点仅在父节点被保留时才可能出现）。
 */
export function filterTaskTree(taskList: Task[], predicate: (task: Task) => boolean): Task[] {
  return taskList
    .filter((task) => predicate(task))
    .map((task) => ({
      ...task,
      subTasks: task.subTasks ? filterTaskTree(task.subTasks, predicate) : []
    }))
}
