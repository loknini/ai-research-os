# 前端架构与设计系统

> 目录：`frontend/src`；数量与版本以 `docs/_meta.json` 为准（当前 Hubs=12，版本 0.5.0）。
> 核对日期：2026-09-28

---

## 1. 技术栈

### 运行时依赖

| 包 | 版本 | 用途 |
|---|---|---|
| `react` / `react-dom` | ^18.2 | UI 框架（`createRoot` + StrictMode） |
| `react-router-dom` | ^6.22 | 路由 |
| `@xyflow/react` | ^12.11 | 专家团队 DAG 画布、连线与节点布局 |
| `zustand` | ^4.5 | 状态管理（`devtools` + `persist`） |
| `@radix-ui/react-scroll-area` `-separator` `-slot` | — | shadcn 组件底座 |
| `class-variance-authority` | ^0.7 | 变体样式（button / badge） |
| `clsx` + `tailwind-merge` | — | `cn()` 类名合并 |
| `lucide-react` | ^0.344 | 全站唯一图标库 |
| `react-markdown` | ^10.1 | Markdown 渲染 |
| `react-syntax-highlighter` | ^16.1 | 代码高亮（Prism + oneDark） |
| `@uiw/react-markdown-editor` | ^6.1 | 笔记编辑器 |
| `react-pdf` | ^10.4 | PDF 预览 |
| `tailwindcss-animate` | ^1.0 | 动画插件 |

**刻意没有的东西**：完整 UI 组件库（shadcn 是手写复制进仓库的源码，不是依赖）、通用图表库（`@xyflow/react` 只用于专家团队 DAG）、数学公式渲染库（KaTeX/MathJax 未接入，公式 Hub 的 `LatexPreview` 目前是纯文本回显）。

### 研发工作区与浮动助手

- `DevelopmentWorkspace` 位于软件项目详情中，负责工作区检查、团队选择、运行轮询、步骤/命令日志、差异审阅、继续/取消和显式应用。
- 团队卡片按 `acceptedContexts` 生成中文“去使用”深链；目标 Hub 消费 `action/teamId` 参数一次并预选团队。
- 浮动 `ChatPanel` 与 Chat Hub 共享 AppStore 中的会话 ID 和模块级流式生成管理器；浮窗创建、发送和展开不会产生第二套聊天历史。

### 开发依赖

`vite ^5.1` · `typescript ^5.3` · `tailwindcss ^3.4` · `postcss` + `autoprefixer` · `eslint ^8.56` + `@typescript-eslint/*` + react-hooks / react-refresh 插件

### 命令

```bash
npm run dev       # vite，:5173
npm run build     # tsc && vite build → dist/
npm run preview   # vite preview
npm run lint      # eslint --max-warnings 0
```

### 构建配置 `vite.config.ts`

- 别名 `@` → `./src`（`tsconfig.json` 同步 `paths`）
- server：`port 5173`、`host: true`（监听 0.0.0.0，内网可访问）
- **代理**：`/api` → `process.env.VITE_API_TARGET || 'http://localhost:8000'`，`changeOrigin: true`；`configure` 钩子强制在 `proxyReq` 上加 `Accept: text/event-stream`，用于 **SSE 透传防缓冲**
- build：`outDir: 'dist'`、`sourcemap: true`

`tsconfig.json` 开启 `strict` + `noUnusedLocals` + `noUnusedParameters` + `noFallthroughCasesInSwitch`——这是本项目最重要的重构护栏。

---

## 2. 目录结构

```
src/
├── main.tsx              入口
├── App.tsx               路由表 + 全局布局 + 全局挂件；挂载后端健康检查
├── hubs/                 12 个功能中心（业务主体）
├── components/
│   ├── ui/               13 个 shadcn 风格基元（手写）
│   ├── layout/           sidebar.tsx / header.tsx
│   ├── agent/            agent-workflow.tsx / generation-watcher.tsx
│   ├── chat/             chat-panel.tsx（右下角悬浮）
│   ├── paper/            paper-card.tsx
│   ├── search/           command-palette.tsx（Cmd+K）
│   ├── SpaceGate.tsx     首屏空间口令守卫
│   └── ErrorBoundary.tsx 顶层错误边界（唯一 class 组件）
├── stores/               appStore.ts（含 useChatStore）/ generationStore.ts
├── services/             api.ts / adminAccess.ts / cronApi.ts
├── types/index.ts        全局类型（268 行）
├── utils/                index.ts（13 个工具函数）/ performance.ts（储备工具箱）
└── index.css             Tailwind + 主题 token + .glass 材质
```

> **Hook 组织**：业务 hook 优先下沉到各 Hub 的 `hooks/` 子目录；顶级 `hooks/` 只保留跨 Hub 复用项（当前为 `usePapers.ts`），另有少量简单 hook 内联在组件文件中。

---

## 3. Hub 与路由

### 3.1 路由表（`App.tsx`，12 个 Hub）

| 路径 | Hub | 侧边栏名称 |
|---|---|---|
| `/` | dashboard | 仪表盘 |
| `/chat` | chat | AI 助手 |
| `/paper` | paper | 论文中心 |
| `/software` | software | 软件开发 |
| `/experiment` | experiment | 实验管理 |
| `/knowledge` | knowledge | 知识库 |
| `/formula` | formula | 公式识别 |
| `/citation` | citation | 引用生成 |
| `/task` | task | 任务清单 |
| `/agent-runs` | agent-runs | 运行历史 |
| `/teams` | teams | 专家团队 |
| `/settings` | settings | （在侧边栏 footer） |

无嵌套路由；12 个 Hub 均以 `React.lazy` 做路由级代码分割，`path="*"` 由 NotFound 页面兜底。`/software` 与 `/experiment` 是指向合并后 `/lab` 的兼容重定向。

### 3.2 App 组件层次

```
<Router>
  <BackendHealthMonitor/>        挂载时一次性 GET /api/healthz
  <GenerationWatcher/>           2s 轮询在途 Agent run，完成时 toast
  <SpaceGate>                    spaceKey 为空时全屏拦截
    <div flex h-screen>
      <Sidebar/>                 可拖拽调宽 + 后端状态灯
      <main>
        <ErrorBoundary>
          <Routes/>
      <GlobalToastContainer/>
      <ChatPanel/>               右下角悬浮聊天
      <CommandPalette isGlobal/> Cmd+K
```

### 3.3 barrel 拆分现状

**已拆分的 6 个**（入口只负责导出或页面编排）：

| Hub | 结构 |
|---|---|
| `paper/` | `PaperHub.tsx`(容器) · `config.ts` · `types.ts` · `hooks/usePaperData.ts` · `services/papersApi.ts` · `components/PaperFilters` `FetchPapersDialog` |
| `task/` | `TaskHub.tsx` · `config.ts` · `hooks/useTaskData.ts` · `services/tasksApi.ts` · `utils/taskTree.ts` · `components/TaskItem`(递归) `TaskForm` |
| `knowledge/` | `KnowledgeHub.tsx` · `config.ts` · `types.ts` · `hooks/useKnowledgeData.ts` · `services/notesApi.ts` `obsidianApi.ts` · `utils/obsidianTree.ts` · `components/NoteCard` `NoteEditor` `ObsidianFileBrowser` `ObsidianFileViewer` `ServerDirectoryPicker` `VaultSelectorDialog` |
| `software/` | `SoftwareHub.tsx` · `config.ts` · `hooks/useSoftwareData.ts` · `services/projectsApi.ts` · `components/ProjectCard` `ProjectDetail` `ProjectForm` `IdeaFormDialog` |
| `chat/` | `ChatHub.tsx`（页面编排）· `hooks/useChatController.ts` · `services/chatApi.ts` `chatGenerationManager.ts` · 侧栏/顶部/消息列表/输入区等组件 |
| `settings/` | `index.tsx`（页面编排）· `hooks/useSettingsController.ts` · 通用/集成/扩展/RAG 面板及独立管理组件 |

**仍以单入口组件为主的 5 个**：`dashboard` · `experiment` · `formula` · `citation` · `agent-runs`。

拆分策略是**零破坏性搬移**：barrel 保持导入路径不变，各拆分文件顶部注释标注了原 monolith 的行号区间。

**新增 Hub 时的标准结构**：

```
hubs/<name>/
├── index.tsx          export { default } from './XxxHub'
├── XxxHub.tsx         容器组件（状态编排 + 布局）
├── config.ts          常量配置（STATUS_CONFIG 等）
├── types.ts           本 Hub 局部类型
├── hooks/useXxxData   派生状态（stats / filtered / 批量操作）
├── services/xxxApi.ts 领域 API 调用（统一委托 services/api.ts）
└── components/        展示组件
```

---

## 4. 状态管理

### `stores/appStore.ts`

**`useAppStore`** — `create()(devtools(persist(...)))`

| 分组 | 状态 |
|---|---|
| 连接 | `isConnected` / `isConnecting` / `connectionError` |
| 导航 | `currentHub` / `sidebarCollapsed` / `sidebarWidth`(clamp 180–360) |
| 空间 | `spaceKey`（默认 `''`） |
| 数据缓存 | `papers` / `experiments` / `projects` / `tasks` / `skills` |
| 加载态 | `isLoadingPapers` / `isLoadingExperiments` |

**持久化**：localStorage key `ai-research-os-storage`，`partialize` 只落盘 4 个字段——`currentHub` / `spaceKey` / `sidebarCollapsed` / `sidebarWidth`。业务数据不落盘，刷新后重新从后端拉。

**`useChatStore`**（同文件）— 仅 devtools 不持久化，`messages` / `isProcessing`。**只服务于右下角悬浮 ChatPanel**，与 `/chat` 路由的 ChatHub 是两套独立体系。

### `stores/generationStore.ts`

统一的「异步生成观察器」状态。

```ts
type GenType = 'chat' | 'agent'
interface WatchedGen { id, type, sourcePath, label, status, target? }
```

`registerGeneration` / `setStatus` / `markNotified` / `unregister`。
`sourcePath` 记录发起页面路径，watcher 据此判断用户是否已离开——**留在发起界面不打扰，离开后完成才弹 toast**。

---

## 5. API 层

### 5.1 唯一 HTTP transport：`services/api.ts`

所有业务请求显式调用 `apiRequest` / `requestJson` / `requestVoid` / `uploadForm` / `downloadBlob` / `openEventStream`，不再 monkey-patch `window.fetch`：

1. **请求头注入** — 仅对同源 `/api` 请求注入归一化后的 `X-Space-Key` 和会话级 `X-Admin-Token`，不会把本地凭据带到跨域 URL。
2. **统一适配** — transport 负责连接状态、结构化错误、超时与取消，并为 JSON、FormData、Blob 和 SSE 提供明确入口。
3. **架构门禁** — ESLint 与 `scripts/check-frontend-boundaries.mjs` 禁止业务源码直接调用 `fetch`，并阻止恢复旧 `apiMonitor.ts`。

### 5.2 调用形态

项目不引入 axios；领域 service 与少量组件内请求都调用统一 transport，并继续使用相对 `/api/...` 路径，依赖 Vite 代理（开发）或同源托管（生产）。跨 Hub 的认证、隔离、错误和连接状态语义只在 `services/api.ts` 实现一次。

### 5.3 两套流式协议（注意区分）

| 场景 | 端点 | 协议 | 解析位置 |
|---|---|---|---|
| 聊天 | `POST /api/chat/completions/stream` | **SSE**（`data:` JSON 帧；解析器兼容历史裸 JSON 行） | `hubs/chat/services/chatApi.ts` |
| Agent | `GET /api/agent/runs/:id/stream` | **标准 SSE**（`data: ` 前缀） | `components/agent/agent-workflow.tsx` |

两者都用 `response.body.getReader()` + `TextDecoder` 手写行缓冲（`buffer.split('\n')`，`lines.pop()` 保留半行）。**全站不使用原生 `EventSource`**——因为需要 POST 和自定义请求头。

Chat 正文只展示自然语言与结构化的“思考过程”工具状态；模型误输出的
`<tool_call>/<function>/<parameter>` 原始协议会在实时渲染、复制和消息落库前清除，
生产界面不提供原始协议调试面板。历史会话中已经保存的协议痕迹也会在读取渲染时隐藏。

Chat 顶部的上下文圆环明确区分两类指标：“下轮请求上下文（估算）”表示下一次请求
相对配置窗口的近似占用；“本轮模型调用累计”来自供应商 usage，会累计一次用户提问中
全部 ReAct/收尾请求并显示请求次数。“会话累计（已计量）”只统计启用 usage 记录后、
且供应商确实返回用量的轮次，旧会话数据不会伪造补算。

**轮询兜底**：`generation-watcher.tsx` 每 2s 轮询 `GET /api/agent/runs/:id`，终态且 `sourcePath !== location.pathname` 且未通知过 → 弹 toast（带「查看」按钮跳转），随后 `unregister`。

### 5.4 错误处理三层

| 层 | 实现 | 行为 |
|---|---|---|
| 渲染 | `ErrorBoundary`（只包 `<Routes>`） | 单 Hub 崩溃不白屏，显示红卡片 + 重试 |
| 网络 | 各 service 内 `try/catch` | **降级返回安全默认值**（`[]` / `false` / `null`） |
| 提示 | `toast({variant:'error'})` | 用户可见反馈 |

无全局错误拦截器。

---

## 6. 组件层

### `components/ui/` — 13 个手写基元

`button` · `badge` · `card` · `input` · `scroll-area` · `separator` · `skeleton` · `toast` · `confirm-dialog` · `pdf-viewer` · `markdown-editor` · `version-history` · `tag-system`

值得注意的几个：

- **`toast.tsx` 有两套 API 并存**：模块级发布订阅（全局 `toast({title, description, variant, action})` + `GlobalToastContainer`，3s 自动消失）与旧的局部 `useToast()`（返回 `{showToast, ToastContainer}`）。ChatHub / PaperHub / Formula / Citation 用后者，其余用前者。
- **`pdf-viewer.tsx`**：翻页 / 缩放（0.2 步进，上限 3.0）/ 下载；worker 已本地打包（`pdfjs-dist/build/pdf.worker.min.mjs?url`，见根目录 `CHANGELOG.md` 的 T2 核销记录），不再依赖 CDN。
- **`version-history.tsx`**：对接 `/api/versions/*`，支持 note / task / project，**目前仅 TaskHub 接入**。
- **`tag-system.tsx`**：212 行完整实现，**当前零引用**（各 Hub 用自己的裸 input 标签逻辑）。

### 业务组件

| 文件 | 职责 |
|---|---|
| `SpaceGate.tsx` | 首屏空间口令守卫。`spaceKey` 为空时全屏遮罩拦截整个应用（保证不会发出缺头请求）；解析 URL `?space=` 自动进入；最少 4 字符 |
| `layout/header.tsx` | title/description/actions 三段式玻璃顶栏 + 私有 `SpaceIndicator`（切换/新建/分享空间，`createPortal` 下拉、视口边界翻转、分享生成 `?space=xxx` 链接写剪贴板） |
| `layout/sidebar.tsx` | 可拖拽调宽（鼠标+触摸，180–360，低于 110 自动折叠到 72）+ 后端状态灯 |
| `agent/agent-workflow.tsx` | 多 Agent 协作面板：发起 run → 登记 generationStore → 消费 SSE → 渲染角色时间线 → 支持取消 |
| `chat/chat-panel.tsx` | 右下角悬浮聊天，含 6 条快捷命令 |
| `search/command-palette.tsx` | Cmd/Ctrl+K 全局搜索，`createPortal` 渲染，调 `/api/search` |
| `paper/paper-card.tsx` | 论文卡片，`React.memo` 包裹 |

---

## 7. 设计系统

**设计语言基准：苹果 HIG 三支柱 Clarity / Deference / Depth**，目标是去掉「AI 生成式模板味」。

### 字体

| 用途 | 字体 | 类名 |
|---|---|---|
| 正文 | **Manrope** | `font-sans`（默认） |
| 展示 / 大数字 / Logo | **Space Grotesk** | `font-display` |

经 `index.html` 的 Google Fonts CDN 注入。**离线环境需自托管**，否则回退系统字体。禁用 Inter。

### 颜色 token（`index.css`，HSL 分量格式配合 `hsl(var(--x))`）

| 变量 | 浅色 Apple Light | 深色 Pro Graphite |
|---|---|---|
| `--background` | `240 9% 96%` | `240 8% 9%` |
| `--foreground` | `240 8% 12%`（近黑 #1D1D1F） | `240 6% 92%` |
| `--card` | `0 0% 100%` | `240 6% 14%` |
| `--primary` | `211 100% 52%`（Apple 蓝 #0A84FF） | `211 100% 58%` |
| `--muted-foreground` | `240 4% 46%` | `240 5% 60%` |
| `--destructive` | `4 76% 56%` | `4 70% 58%` |
| `--border` | `240 6% 85%` | `240 5% 22%` |
| `--radius` | `0.75rem` | 继承 |

**原则**：单一冷蓝强调色；红色只用于错误态；**绝不用纯白平铺**——body 叠三层 `radial-gradient` 氛围晕染（左上冷蓝 / 右上淡紫 / 右下青，`background-attachment: fixed`）。

### 材质与动效

- **`.glass`**（Depth 支柱）：`rgba` 半透明底 + `backdrop-filter: blur(20px) saturate(180%)` + 1px 半透明边框 + 内高光 inset 阴影 + 柔和外投影。用于 Sidebar / Header / Dashboard 面板 / SpaceIndicator 下拉。
- **`.row-hover`**：列表行极淡悬停底纹。
- **`fade-up`**：`0.5s cubic-bezier(0.22, 1, 0.36, 1)`，从 `opacity:0, translateY(12px)` 进场，用于交错出现。
- **无障碍不可妥协**：`@media (prefers-reduced-motion: reduce)` 内强制停用 `fade-up`。

### 圆角刻度（`tailwind.config.js`）

`lg: var(--radius)` · `md: calc(var(--radius) - 2px)` · `sm: calc(var(--radius) - 4px)`，额外扩展 `xl: 1rem` · `2xl: 1.25rem` · `3xl: 1.5rem`。

### 暗色模式

`.dark` token 已完备，通过 `stores/themeStore.ts` + `App.tsx:ThemeSync` + `components/layout/theme-toggle.tsx` 实现 `light/dark/system` 切换并持久化，`main.tsx` 首屏 `applyTheme` 防闪烁。详见根目录 `CHANGELOG.md` 的 T4 核销记录。

---

## 8. 类型与工具

### `types/index.ts`（268 行，全局唯一类型文件）

`Paper` · `SoftwareProject` + `ProjectArchitecture` / `ArchitectureComponent` / `TechChoice` / `ProjectFeature` / `ProjectMilestone` · `Task` + `TaskFilter` / `TaskStats` · `Note` · `Experiment` / `ExperimentRun` · `Skill` · `AppState` · `ChatMessage`

局部类型分散在各 Hub 的 `types.ts` 或内联于 monolith Hub 中。
> ⚠️ `hubs/citation/index.tsx` 内的局部 `Paper` 接口与全局 `types.Paper` **同名但结构完全不同**（前者是 DOI 元数据），阅读时注意来源。

### `utils/index.ts`（13 个函数）

`cn()`（最高频） · `formatDate` · `formatRelativeTime` · `truncateText` · `generateId` · `deepClone` · `debounce` · `throttle` · `saveToLocalStorage` / `loadFromLocalStorage` · `downloadFile` · `formatFileSize` · `isValidArxivId` · `extractArxivId`

### `utils/performance.ts`（397 行）

`Cache<T>`（LRU + TTL）· `globalCache` · `cached()` · 虚拟滚动 `calculateVirtualScroll` / `useVirtualScroll` · `useLazyLoad` · `batchGenerator` / `loadInBatches` · `PerformanceMonitor`

> **当前几乎无引用**（论文列表用的是自己的分页而非虚拟滚动），属储备工具箱。`debounce`/`throttle` 与 `utils/index.ts` 重复实现。

### 已移除的规则式助手入口

旧 `services/aiAgent.ts` 与 `POST /api/agent/run` 已删除。当前悬浮 `ChatPanel` 与 ChatHub 共享 `chatGenerationManager` 和同一套会话 API；复杂任务统一从 Agent/DAG 入口发起。

---

## 9. 验证

前端使用 Vitest，并将静态检查、单测、架构边界与生产构建汇总为一条命令：

```bash
cd frontend
npm run verify       # lint + vitest + 架构边界 + tsc + vite build
```

其中 `check:architecture` 保证只有统一 transport 可以调用原生 `fetch`，并限制 Chat/Settings 页面入口重新膨胀。之后仍需按改动范围人工冒烟 CRUD、筛选、弹窗、分页、流式对话与空间切换。
