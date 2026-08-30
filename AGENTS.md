# AGENTS.md - AI-Research-OS 项目说明

> 本文档面向 **AI 协作者 / 自动化 Agent**。架构、数据模型、API、Agent/LLM 设计与前端细节见 [`docs/`](./docs/README.md)，本文只给概览与开发规范。

## 项目概览

**项目名称**: AI-Research-OS
**项目定位**: 面向研究生与科研工作者的**一站式 AI 研究与开发工作台**
**核心理念**: 可视化、模块化、可扩展的本地优先工作台（不登录、零重依赖、多人内网可用）

**三条硬约束**
1. **本地优先**：核心功能只依赖 Node + Python + SQLite，不绑定任何外部服务。
2. **零重依赖**：LLM 走 `urllib` 自研客户端，不引入 `openai` SDK；后端第三方依赖极少。
3. **不登录多人可用**：靠 space-key 软隔离，而非账号体系；内网共享同一部署。

---

## 项目结构

```
D:\project\ai-research-os/
├── frontend/              # React 18 + TypeScript 前端
│   └── src/
│       ├── hubs/          # 功能模块（Dashboard/Paper/Teams/Lab/... 共 12 个 Hub）
│       ├── components/    # 通用 / 布局 / UI 组件（含 .glass 设计系统）
│       ├── stores/        # Zustand 状态管理（按 Hub 拆分）
│       ├── services/      # API 客户端（apiMonitor.ts 单点注入 X-Space-Key）
│       ├── hooks/         # 少量跨 Hub hooks（大多内聚在各 Hub）
│       ├── types/         # TypeScript 类型定义
│       └── utils/         # 工具函数
├── backend/               # 独立 FastAPI 后端（uvicorn backend.server.main:app，端口 8000，多 worker）
│   ├── server/
│   │   ├── main.py        # 应用入口，挂载 /api 路由 + 静态托管前端
│   │   ├── config.py      # 配置单例（LLM_* / DB_PATH / CORS / DATA_DIR）
│   │   ├── llm.py         # LLM 客户端（OpenAI 兼容，urllib，零额外依赖）
│   │   ├── db.py          # 引导 database.py + init_db()
│   │   ├── deps.py        # get_space_id 空间隔离依赖
│   │   ├── agent_runner.py# 后台非阻塞 Agent / DAG 运行器
│   │   ├── agent_teams.py # 团队定义校验、内置团队与上下文解析
│   │   └── routers/       # tasks / projects / notes / papers / chat / agent / settings ...
│   ├── skills/            # Agent Skills（backend/skills/<name>/SKILL.md，零依赖约定）
│   └── requirements.txt   # 后端依赖（不含 openai）
├── scripts/               # Python 后端脚本（业务逻辑，输出 JSON 供后端解析）
│   ├── database.py        # SQLite 数据模型（aiosqlite 异步，WAL）
│   ├── fetch_arxiv.py     # arXiv 抓取
│   ├── agent_service.py   # 兼容入口；可配置执行器真身位于 backend/server/
│   └── ...
├── data/                  # 数据存储（SQLite / PDF / 导出，已 gitignore）
├── docs/                  # 架构与设计文档（见 docs/README.md 索引）
├── .archive/              # 已归档的旧/过时文档（gitignored）
├── AGENTS.md              # 本文
├── CHANGELOG.md           # 版本与里程碑变更
├── README.md              # 面向人类用户的项目说明
└── start.ps1 / start.sh   # 一键启动脚本
```

> **模块导入约定（2026-07-31 已规范化）**：各模块使用**正规包导入**，无 `sys.path` 注入 hack（`backend` 与 `scripts` 均为正规包，各有 `__init__.py`）。
> - `backend/server/` 内模块互相引用：`from . import x`（包内相对），例如 `agent_runner.py` 用 `from . import agent_service, db`；`from .. import x` 现在也可用（`backend` 是正规包）。
> - 引用顶层 `scripts/` 包：`from scripts import database` / `from scripts.chat_agent_stream import execute_tool` 等。
> - Agent 角色管线真身在 `backend/server/agent_service.py`（与 server 同包），由 `backend/agent_roles.json` 驱动。

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| **前端** | React 18 + TypeScript + Vite 5 | UI 开发框架 / 构建 |
| | TailwindCSS + shadcn/ui（源码内置） | 样式和组件库（未引入额外 UI 库） |
| | Zustand | 全局状态管理（按 Hub 拆分 store） |
| | React Router v6 | 前端路由 |
| | Vite Proxy | `/api` 转发至 FastAPI 后端（:8000） |
| **后端** | FastAPI + uvicorn（多 worker） | 独立后端服务 |
| | LLM 客户端 (llm.py) | OpenAI 兼容接口，urllib 实现，零新增依赖 |
| | aiosqlite + SQLite (WAL) | 本地数据持久化，每请求独立连接 |
| | SSE 流式 | Chat 与 Agent 均使用 SSE；前端分别按各自事件语义解析 |
| **存储** | SQLite + 文件系统 | 本地数据；按 space-key 软隔离（29 张业务表均含 `space_id`） |

---

## 核心功能模块（Hubs）

| Hub | 功能 | 状态 |
|-----|------|------|
| **Dashboard** | 首页仪表盘、全局统计 | ✅ 已实现 |
| **Paper Hub** | 论文抓取、筛选、AI 总结、PDF 预览 | ✅ 已实现 |
| **Task Hub** | 任务管理、子任务、优先级、AI 建议 | ✅ 已实现 |
| **Software Hub** | 从 Idea 到开发计划（可配置专家团队） | ✅ 已实现（后台运行、显式应用） |
| **Knowledge Hub** | 研究笔记、Markdown、版本历史 | ✅ 已实现 |
| **Experiment Hub** | SwanLab 实验追踪、对比 | ✅ 已实现（需 SwanLab Key） |
| **Chat Hub** | ReAct 对话 + 工具调用 | ✅ 已实现 |
| **Formula Hub** | 公式 OCR → LaTeX | ✅ 已实现 |
| **Citation Hub** | 引用检索与 BibTeX 生成 | ✅ 已实现 |
| **Settings Hub** | LLM/SwanLab 配置、数据备份迁移 | ✅ 已实现 |
| **Agent Runs** | 后台运行历史、进度、完成提醒 | ✅ 已实现 |
| **Expert Teams** | 可视化 DAG、角色模板、导入导出 | ✅ 已实现 |

---

## 环境要求

### 已安装工具

| 工具 | 版本 | 用途 |
|------|------|------|
| Git | 2.53.0.windows.2 | 版本控制 |
| Python | 3.12.3 | 后端服务与脚本 |
| Node.js | ≥ 18（推荐 22） | 前端运行时 |
| curl | 8.13.0 | HTTP 请求（联调 / 验收） |

### 需要安装

- **Node.js** >= 18（前端运行时需要）
- **Python 后端依赖**：`pip install -r backend/requirements.txt`

---

## 快速开始

### 1. 安装依赖

```powershell
# 前端
cd frontend
npm install

# 后端
pip install -r backend/requirements.txt
```

### 2. 配置 LLM

首次启动后在界面「设置 → LLM API 配置」中填写 Base URL / API Key / 模型名（支持点击「获取模型」自动拉取可用模型列表），保存后重启后端生效。

也可以直接编辑 `backend/.env`（参考 `backend/.env.example`，内含硅基流动 / 智谱 / Ollama 三套预设）。

### 3. 启动开发服务器

```powershell
# 一键启动（后端 + 前端）
.\start.ps1

# 或手动分别启动：
# 终端 1: 启动 FastAPI 后端（多 worker）
python -m uvicorn backend.server.main:app --port 8000 --workers 4

# 终端 2: 启动前端开发服务器
cd frontend
npm run dev
```

### 4. 访问应用

打开浏览器访问: `http://localhost:5173`

---

## 开发规范

### 命名规范

- **组件文件**: PascalCase (e.g., `PaperList.tsx`)
- **工具函数**: camelCase (e.g., `fetchArxivPapers`)
- **常量**: UPPER_SNAKE_CASE (e.g., `MAX_PAPER_COUNT`)
- **类型**: PascalCase (e.g., `TPaper`, `IProps`)
- **后端模块**: snake_case (e.g., `chat_agent_stream.py`)

### 代码组织

- 每个 Hub 独立目录，包含页面、组件、Hooks（hook 内聚在 Hub 内，跨 Hub 公共 hook 才放 `src/hooks/`）。
- 通用组件放在 `components/` 目录。
- 类型定义集中在 `types/` 目录。
- 状态管理使用 Zustand，按 Hub 拆分 store。

### 后端铁律

- **禁止 `openai` SDK**：LLM 调用一律走 `backend/server/llm.py`（`urllib` 实现）。
- **数据库操作统一走 `scripts/database.py`**：不要直接散落 SQL。
- **空间隔离**：新增数据表/路由必须加 `space_id` 列并通过 `Depends(get_space_id)` 过滤；系统级接口（healthz/settings/backup/skills/swanlab/citation）可豁免。
- **更新语义**：写操作返回 `rowcount > 0`，不要跨空间返回 True。
- **新增工具 = 新模块**：工具用 `@register_tool` 装饰器写在 `backend/server/tools/<name>.py`（自动发现），不要在 Agent 主循环里硬编码工具分支。
- **工具策略标注**：只读工具 `policy="safe"`；写库等有副作用 `policy="sensitive"`；删除/覆盖等不可逆 `policy="dangerous"`（非 strict 模式自动拦截）。

---

## 关键文件

| 文件 | 说明 |
|------|------|
| `docs/README.md` | 文档索引（架构/数据/API/Agent/前端/运维/技术债） |
| `frontend/src/services/apiMonitor.ts` | 前端 API 客户端，单点注入 `X-Space-Key` |
| `backend/server/` | FastAPI 后端（路由、LLM 客户端、配置、空间隔离依赖） |
| `backend/server/agent_service.py` | 角色化 Multi-Agent 真身（与 server 同包，由 `backend/agent_roles.json` 驱动） |
| `backend/server/tool_registry.py` | **工具注册表 + 审批策略内核**（`@register_tool` / safe-sensitive-dangerous / auto-manual-strict） |
| `backend/server/tools/` | **内置工具目录**（`pkgutil` 自动发现，新增工具零改动主循环） |
| `backend/server/context.py` | **共享上下文管理**（token 估算 / LLM 摘要 / `compact_messages`，Chat 与 Agent 共用） |
| `backend/server/agent_runner.py` | 后台非阻塞 runner（消费 `__approval_required` 审批等待 + `__replay` 落库） |
| `scripts/database.py` | SQLite 数据模型（异步；含 `agent_tool_approvals` / `agent_replay_messages` 表） |
| `scripts/qa_verify_agent_harness.py` | Agent 工程能力回归脚本（审批/重放/上下文/插件化，61 项） |
| `backend/.env` | LLM API 配置（可由设置界面写入） |
| `start.ps1` | 一键启动脚本 |

---

## 参考资源

- [文档索引](./docs/README.md)
- [FastAPI 官方文档](https://fastapi.tiangolo.com)
- [shadcn/ui 组件库](https://ui.shadcn.com)

---

## 备注

- 当前日期：2026-08-26
- 项目状态：功能基本完备，文档基于代码实况重构中
- 版本：v0.5（隔离研发工作区 / 可配置专家团队 / 共享 LLM 助手 / 工具审批）
