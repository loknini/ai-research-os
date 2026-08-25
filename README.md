# AI-Research-OS

> 面向研究生与科研工作者的**一站式 AI 研究与开发工作台** —— 模块化、可视化、AI 驱动。

AI-Research-OS 把论文管理、任务追踪、知识沉淀、实验管理与 AI 辅助软件开发整合到一个工作台中。你可以用它抓取并总结 arXiv 论文、管理研究任务、记录 Markdown 笔记、追踪 SwanLab 实验、对本地文档做 RAG 问答，并用 Multi-Agent 把「想法」拆解成可执行的开发计划，还能用 Cron 定时调度这一切。

**三条设计硬约束**
- **本地优先**：核心功能只依赖 Node + Python + SQLite，不绑定任何外部服务。
- **零重依赖**：LLM 走 `urllib` 自研客户端，不引入 `openai` SDK。
- **不登录多人可用**：靠 space-key 软隔离，内网共享同一部署。

---

## ✨ 核心特性

### 业务域（侧边栏一级导航）

| 页面 | 功能 | 亮点 |
|------|------|------|
| **仪表盘** | 全局概览、待办聚合 | 实时数据卡片、最近动态、跨 Hub 任务聚合 |
| **AI 助手** | 智能对话（Chat Hub） | 真实 LLM 流式响应、ReAct 工具调用、**RAG 文档接地问答**（自动引用标注）、会话分支/重生成 |
| **论文中心** | 论文抓取 / 管理 / 总结 | arXiv 自动抓取、AI 中文总结、PDF 在线预览、标签系统、**BibTeX 引用生成**、引用工具（Citation Hub） |
| **知识库** | 研究笔记管理 | Markdown 编辑器、版本历史对比恢复、**公式 OCR 工具**、Obsidian 联动 |
| **研发实验** | 软件开发 + 实验追踪 | **Architect + Planner + Reviewer Multi-Agent 规划**、任务自动拆解、后台运行、SwanLab 实验对比 |
| **设置** | 全局配置与数据管理 | LLM 连接、集成服务、**RAG 索引源管理**、数据备份迁移、Skill 管理 |

### 工具（Cmd+K 命令面板，不占一级导航）

| 工具 | 说明 |
|------|------|
| 公式识别 | 图片公式 → LaTeX，历史收藏 |
| 引用生成 | 引用检索 → BibTeX / 标准格式 |
| 任务清单 | 独立待办视图（数据与仪表盘/论文联动） |
| 运行历史 | 后台 Agent 运行记录、时间线、审批/回放 |
| 定时任务 | Cron 调度：定时跑命令 / Agent / arXiv 抓取 |

### 全局能力

- ⌨️ **命令面板**：`Ctrl / Cmd + K` 唤起，无输入时浏览分组命令，有输入时跨 Hub 实时搜索（论文 / 任务 / 项目 / 笔记 / 实验）
- 💬 **悬浮 ChatPanel**：右下角常驻 AI 助手
- 🗂️ **版本历史**：论文 / 笔记 / 项目修改自动留痕，可对比、可回滚
- 🤖 **Agent 工程能力（v0.3）**：**工具审批**（safe / sensitive / dangerous 三级策略 + 前端审批卡片）、**可重放日志**（每轮模型实际看到的消息序列落库，可回放）、**上下文管理**（超预算自动 LLM 摘要压缩，不切断 tool 配对）、**插件化工具**（`backend/server/tools/` 新增工具零改动主循环）
- 📚 **RAG 文档检索**：把 PDF / 文本索引进本地向量库（复用 LLM 的 `/v1/embeddings`），Chat 里开「RAG 问答」即可基于你自己的资料回答并标注引用
- ⏰ **Cron 定时调度**：`command` / `agent_run` / `arxiv_fetch` 三种任务，自研零依赖解析器，多 worker 靠乐观锁防重复执行
- 🔐 **space-key 软隔离**：内网多人共享同一服务时，按空间密钥隔离数据，无需登录（见下方「多人 / 内网使用」）

---

## 🏗️ 系统架构

```
┌──────────────────────────────────────────────────────────┐
│               前端层 (React 18 + TypeScript + Vite)         │
│   仪表盘 · AI助手 · 论文中心 · 知识库 · 研发实验 · 设置       │
│   + Cmd+K 命令面板（工具命令：公式/引用/任务/运行历史/Cron）  │
│   开发态: vite dev(:5173) 通过 proxy 把 /api 转发到后端      │
│   生产态: npm run build → dist/ 由后端直接静态托管           │
└───────────────────────────┬──────────────────────────────┘
                             │  HTTP /api/*  (vite proxy → 后端 :8000)
                             │  + 每个请求注入 X-Space-Key 头（空间隔离）
                             ▼
┌──────────────────────────────────────────────────────────┐
│         后端 API 层 (独立 FastAPI + uvicorn :8000)         │
│  · 路由：tasks / papers / projects / notes / chat / agent │
│    / rag / cron / experiments / formula / citation / ...  │
│  · LLM 客户端：urllib 实现的 OpenAI 兼容客户端（零新依赖） │
│  · Agent 工程：tool_registry(审批) / context(压缩) /       │
│    agent_runner(后台) / tools/(插件化) / cron_scheduler    │
│  · space-key 软隔离：处理器级 get_space_id 依赖过滤数据    │
└───────────────────────────┬──────────────────────────────┘
                             │  Python (stdlib + 少量依赖)
                             ▼
┌──────────────────────────────────────────────────────────┐
│              业务逻辑层 (scripts/*.py)                       │
│  database.py · fetch_arxiv.py · summarize_paper.py         │
│  agent_service.py · chat_agent_stream.py · rag_service.py  │
│  swanlab_*.py · formula_service.py · citation_service.py   │
│  obsidian_service.py · qa_verify_*.py（回归验证）          │
└──────────┬───────────────────────────────┬───────────────┘
           │ SQLite (WAL)                   │ 可选外部 LLM / 服务
           ▼                                ▼
   data/ai_research_os.db          OpenAI 兼容 LLM（SiliconFlow /
                                   智谱 / Ollama … 由 LLM_BASE_URL 配置）
                                   SwanLab (实验数据) · 博查/维基 (web_search)
```

**重要区分**
- **核心功能**（论文 / 任务 / 项目 / 笔记 / 实验 / 版本 / 搜索 / Cron 的 command 任务）只依赖 `Node + Python + SQLite`，**不需要**任何外部服务即可运行。
- **AI 功能**（论文 AI 总结、Chat Hub 对话、Multi-Agent 规划、RAG 索引与问答）需要一个 **OpenAI 兼容的 LLM 端点**（默认留空，需在「设置 → LLM API 配置」或 `.env` 中填写；可对接硅基流动 / 智谱 / Ollama 等任意兼容服务）。LLM 连接通过环境变量或 `.env` 配置，**不依赖 `openai` SDK**。
- **实验功能**需要配置 **SwanLab** API Key。
- 前端在 LLM 离线时会优雅降级（连接状态显示 Offline），不会崩溃。

> 更完整的架构、数据模型、API、LLM/Agent 设计与前端说明见 [`docs/`](./docs/README.md) 下的专门文档（含一页式 [`SYSTEM-DESIGN.md`](./docs/SYSTEM-DESIGN.md)）。

---

## 🧰 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18、TypeScript、Vite 5、TailwindCSS + shadcn/ui（源码内置）、Zustand、React Router v6 |
| API 层 | **独立 FastAPI + uvicorn 后端（端口 8000，多 worker）**，开发态前端经 `vite proxy` 转发 `/api` |
| 后端脚本 | Python 3.10+（标准库为主 + 少量第三方库） |
| LLM | 任意 OpenAI 兼容端点（urllib 客户端，零新增依赖；含 embeddings 用于 RAG） |
| 存储 | SQLite（`data/ai_research_os.db`，WAL 模式）+ 文件系统，按 space-key 软隔离 |

---

## 📋 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| **Node.js** | ≥ 18（推荐 20 LTS / 22） | 前端运行时与 Vite |
| **Python** | ≥ 3.10 | 后端服务与脚本（启动脚本会自动创建 `.venv` 虚拟环境，不污染全局） |
| **npm** | 随 Node 自带 | 安装前端依赖 |
| 兼容 LLM 端点 | — | **仅 AI 功能需要**；默认留空，需在「设置 → LLM API 配置」中填写（硅基流动 / 智谱 / Ollama 等任意 OpenAI 兼容服务） |
| SwanLab 账号 | — | **仅实验功能需要** |
| 博查 Bocha Key | — | **仅 Agent 联网搜索需要**（不配置则自动降级 Wikipedia） |

> Windows 用户建议使用 PowerShell 运行 `start.ps1`；macOS / Linux 用户使用 `start.sh` 或手动启动。
> Python 后端依赖见 `backend/requirements.txt`：`fastapi`、`uvicorn[standard]`、`pydantic`、`pydantic-settings`、`python-dotenv`、`requests`、`python-multipart`、`aiosqlite`、`pypdf`（**不含 `openai`**）。

---

## 🚀 安装步骤

### 1. 获取代码

```bash
git clone <your-repo-url> ai-research-os
cd ai-research-os
```

### 2. 一键安装并启动（推荐，Windows）

```powershell
.\start.ps1
```

该脚本会自动完成：检查 Python → 创建项目内 `.venv` 虚拟环境 → 安装后端依赖到 `.venv` → 安装前端依赖 → 创建数据目录 → 启动 FastAPI 后端（多 worker）→ 启动前端开发服务器。**无需手动装依赖**。

macOS / Linux：

```bash
chmod +x start.sh
./start.sh
```

### 3. 手动安装（可选，想完全自己控制时）

```bash
# 前端依赖
cd frontend
npm install

# 后端依赖（建议放进虚拟环境）
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 4. （可选）配置 LLM 以启用 AI 功能

复制示例配置并按需修改：

```bash
cp backend/.env.example .env    # 复制到项目根目录
# 编辑 .env，设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
```

- 默认 LLM 配置为空；推荐启动后在**前端「设置 → LLM API 配置」**中填写（支持硅基流动 / 智谱 / Ollama 等预设一键填充 + 测试连接 + 读取可用模型），保存即生效并写入 `.env`。
- 也可直接编辑 `.env`（参考 `backend/.env.example` 中的四套预设：硅基流动 / 智谱 / Ollama / Agnes AI）。

### 5. 初始化数据目录

```bash
# 创建数据子目录（首次运行也会自动创建）
mkdir -p data/papers/pdfs data/experiments data/software data/knowledge
```

SQLite 数据库会在后端首次启动时自动建表（`backend/server/db.py:init_db()`），无需手工初始化。

---

## ▶️ 运行项目

### 方式一：一键启动脚本

**Windows（PowerShell）**

```powershell
.\start.ps1                        # 启动后端 + 前端
.\start.ps1 -SkipFrontend          # 仅启动后端
.\start.ps1 -SkipBackend           # 仅启动前端（核心功能需另行提供 /api）
.\start.ps1 -ApiPort 9000          # 自定义后端端口
.\start.ps1 -ApiWorkers 4          # 指定 worker 数（默认 min(CPU, 8)）
.\start.ps1 -DataDir D:\Sync\airos-data   # 数据目录指向同步盘（双设备单数据源）
.\start.ps1 -ReuseBackend          # 端口已有健康后端实例时复用，不重启
```

**macOS / Linux（bash）**

```bash
./start.sh                          # 启动后端 + 前端
./start.sh -s                       # 仅启动后端（--skip-frontend）
./start.sh -b                       # 仅启动前端（--skip-backend）
./start.sh -p 9000                  # 自定义后端端口
./start.sh -w 4                     # 指定 worker 数
./start.sh -d ~/Sync/airos-data     # 数据目录指向同步盘
```

> 也可把数据目录路径写进项目根 `.airos-data-dir` 文件（首行即路径），之后直接启动即可，无需每次传参。

### 方式二：手动启动（跨平台）

```bash
# 终端 1：启动 FastAPI 后端（多 worker，生产推荐不加 --reload）
cd ai-research-os
python -m uvicorn backend.server.main:app --host 0.0.0.0 --port 8000 --workers 4
# 开发态可加 --reload；默认访问 http://localhost:8000 ；/api/healthz 检查健康

# 终端 2：启动前端（开发态，/api 经 vite proxy 转发到 :8000）
cd frontend
npm run dev
# 默认访问 http://localhost:5173
```

### 方式三：生产部署（单进程托管，前后端一体）

```bash
# 1. 构建前端（类型检查 + 产物输出到 frontend/dist/）
cd frontend && npm run build

# 2. 仅启动后端（main.py 检测到 dist/ 存在后自动静态托管整个 SPA）
cd ..
python -m uvicorn backend.server.main:app --host 0.0.0.0 --port 8000 --workers 4
# 此时访问 http://localhost:8000 即完整应用；/api/* 与前端同源，无需 CORS
```

> 即使不配置 LLM，论文抓取、任务、笔记、实验（不含 SwanLab 拉取）等核心功能均可正常使用；AI 相关接口会优雅返回降级结果。

---

## 🔐 多人 / 内网使用（space-key 软隔离）

项目定位为**不登录的内网小服务**：同一份部署在局域网内被多人访问，靠 **space-key** 做数据软隔离，而非账号体系。

- **身份即密钥**：首次进入会提示填写一个稳定的空间密钥（或携带 `?space=<key>` 共享链接）。密钥会被 `trim + lower` 后直接作为 `space_id`（不哈希、允许中文/符号、最小长度 4）。
- **数据隔离**：所有读写都按 `space_id` 过滤；存量数据归入默认空间 `__default__`。系统级配置（LLM、CORS、`.env`）保持全局不隔离。
- **跨设备互通**：同一 space-key 在不同设备 / 浏览器即同一份数据，便于团队共享某个研究空间。
- **共享链接**：在界面里复制「分享空间」链接（`?space=<key>`），对方打开即进入同一空间。

> 边界说明：本期未实现空间重命名/删除、按空间备份、空间级 LLM 配置（P2）。同一时刻仍遵循 SQLite「单写源」纪律（见下节备份与同步）。

---

## 📦 数据备份与多设备同步

你的所有研究数据（论文 / 任务 / 笔记 / 实验 / 知识库）都存放在后端数据目录 `DATA_DIR`（默认 `<项目根>/data`，含 SQLite 数据库 `ai_research_os.db`）。以下三种方式可保证数据不丢失、可在多设备间迁移。

### 1. 把数据目录指向同步盘（零代码，已原生支持）

后端通过环境变量 `DATA_DIR` 定位数据目录，启动时若目录不存在会自动建库建表。因此**无需改任何代码**，只要把 `DATA_DIR` 指到一个被 Syncthing / OneDrive / iCloud 等实时同步的目录即可：

```powershell
# Windows (PowerShell) —— 在启动前设置，建议写进 start.ps1 或系统环境变量
set DATA_DIR=D:\你的同步盘\airos-data
```

```bash
# Linux / macOS (bash/zsh)
export DATA_DIR=~/synced/airos-data
```

> ⚠️ **不要在两台机器上同时运行 app 并写入同一个同步目录**：SQLite 不支持多进程并发写，同时写会导致数据库损坏。正确做法是「一台写、其余只读」，或在一台做完改动、同步完成后，再在另一台启动。

### 2. 应用内导出 / 导入备份包（迁移到新设备最稳妥）

打开 **「设置 → 数据备份与迁移」** 卡片：

- **导出备份**：把 `DATA_DIR` 整个打成 zip 下载（自动剔除 `.git` / `.swanlab` / `.cache` / `__pycache__` 等垃圾与缓存目录，并附 `manifest.json` 清单）。
- **导入备份**：选择旧机器导出的 zip，后端会**先自动备份当前数据到 `<DATA_DIR 同级>/.backup-时间戳`**，再把备份包内容覆盖进 `DATA_DIR`。若导入时应用正占用数据库导致写入失败，会给出明确提示——此时请停止 app 后重新导入 / 重启以加载新数据。

对应接口（供脚本 / 自动化调用）：

```bash
# 导出（返回 zip 字节流，浏览器会触发下载）
curl -X POST http://localhost:8000/api/backup/export -o airos-backup.zip

# 导入（字段名 file，仅接受 .zip，上限 500MB）
curl -X POST http://localhost:8000/api/backup/import -F "file=@airos-backup.zip"
```

### 3. 后端依赖隔离（venv，不污染全局 Python）

`start.ps1` / `start.sh` 首次运行时会自动在项目根创建 `.venv` 虚拟环境，并把 `backend/requirements.txt` 的依赖安装进该虚拟环境，之后所有后端操作（检测 uvicorn / 启动 uvicorn）都使用 `.venv` 内的解释器——**不会污染系统全局 Python**。正式部署（Docker）时容器本身天然隔离，无需额外处理。

> 想完全手动控制？参考上方「方式二：手动启动」，用你自己的虚拟环境 `pip install -r backend/requirements.txt` 即可。

---

## 📡 双设备实时同步（Syncthing）

把数据目录指向同步盘后，最顺手的「单数据源」方案是用 **Syncthing** 在两台机器之间实时同步 `DATA_DIR`。这跟上一节「指向同步盘」是同一件事，只是把"手动同步 / 云盘"换成了"去中心化实时同步"，更适合日常双设备办公。

### 1. 为什么用 Syncthing

- 上一节的「应用内导出 / 导入备份包」是**整盘覆盖、不合并**——换机可以，但日常来回倒腾会丢改动。
- 日常双设备办公的正确姿势是 **单数据源**：把 `DATA_DIR` 指到 Syncthing 同步盘，两台机器共用同一份 SQLite 数据库与文件，从根上消灭"哪边才是最新"的不一致。
- Syncthing 免费、开源、去中心化，**不绑定任何云账号**，数据只在你自己的设备之间流动。

### 2. 实操步骤（Windows + macOS，Linux 同理）

1. 在两台机器都装上 Syncthing（官网下载，一路下一步即可）。
2. 选一个同步文件夹（例如 Windows `D:\Sync\airos-data`、macOS `~/Sync/airos-data`），在 Syncthing 里把它加为"需要同步的文件夹"，并互相添加对方的设备 ID（扫码 / 粘贴即可）。
3. 启动本应用时把 `DATA_DIR` 指到该目录：Windows `.\start.ps1 -DataDir D:\Sync\airos-data`；macOS / Linux `./start.sh -d ~/Sync/airos-data`。（也可把路径写进项目根 `.airos-data-dir` 文件，首行填路径，"设一次忘掉"。）
4. 首次在一台机器启动会自动建库建表，Syncthing 把它同步到另一台——之后两边就是同一份数据。

### 3. ⚠️ 铁律：同一时刻只能有一台机器在写这个库

SQLite **不支持多进程并发写**。两个 app 进程同时写一个 `.db` 文件，有数据库损坏、数据丢失的风险。

> **离开工位前，关掉那台机器的 app**（或至少别两台同时开着写）。等到另一台要用时再启动。这是用"单数据源"方案唯一的纪律要求。

### 4. 冲突了怎么办

如果不小心两台同时写了，Syncthing 可能对发生冲突的文件生成 `.sync-conflict-<时间戳>` 副本。处理步骤：

1. **先停掉两台机器的 app**（避免继续写入）。
2. 对比 `.sync-conflict` 副本与原始文件，保留你想要的那一份。
3. 删掉冲突副本，再正常启动其中一台。

> 应用内「导出 / 导入备份包」仍可作一次性的换机兜底（见上一节），但它会整体覆盖，日常别依赖它来合并改动。

### 5. 适用边界

- 纯本地、个人多设备（Windows / macOS / Linux）实时同步的**首选**。
- 目前**不含手机端**：如果要手机也能看 / 改，那是另一回事（T2 外置后端方案，暂不在本期范围）。

---

## 📖 使用示例

### A. 界面操作

**论文工作流**
1. **抓取论文**：进入 *论文中心* → 点击「抓取论文」→ 设置关键词 / 数量 → 自动存入数据库并展示。
2. **AI 总结**：在论文列表点击「总结」，调用配置的 LLM 生成结构化中文摘要（研究背景 / 核心方法 / 贡献 / 实验 / 局限）。
3. **导出引用**：点击论文卡片的「引用」按钮，生成 BibTeX 并一键回填到笔记。

**Agent 开发工作流**
4. **多 Agent 规划**：进入 *研发实验* → 新建项目并描述想法 → Architect + Planner + Reviewer 协作输出技术方案与任务清单（可后台运行，完成时 toast 提醒）。
5. **工具审批**：若后端开启 `manual` / `strict` 审批模式，Agent 要写库时会弹出「允许执行 / 拒绝」审批卡片；拒绝即 fail-closed 不执行。
6. **查看回放**：在 *运行历史* 打开某次运行 → 「工具审批」tab 看审批决策，「会话回放」tab 看每轮模型实际看到的消息序列。

**RAG 文档问答**
7. **建立索引**：*设置 → RAG 文档检索*（或直接访问 `#rag`）→ 录入要索引的本地 PDF / 文本目录 → 触发索引（复用 LLM embeddings，失败自动降级关键词检索）。
8. **接地问答**：进入 *AI 助手* → 开启「RAG 问答」开关（可勾选来源）→ 提问。回答会以 `[n]` 标注引用，悬浮查看原文片段；会话切换时 RAG 设置自动恢复。

**自动化**
9. **定时任务**：打开 *定时任务*（Cmd+K 搜「cron」）→ 新建任务，三种类型任选：`command`（执行任意命令）/ `agent_run`（跑多 Agent 管线）/ `arxiv_fetch`（定时抓论文入库）→ 设 Cron 表达式（如 `0 9 * * 1` 每周一 9 点）→ 查看执行历史。

**通用**
10. **全局搜索**：按 `Ctrl / Cmd + K`，输入关键词跨所有 Hub 检索，或直接 ↑↓ + Enter 直达命令。
11. **会话式助手**：右下角 ChatPanel 或 *AI 助手*，可让 AI「帮我抓取关于 diffusion 的最新论文」「创建一个任务：复现 XXX」。

### B. 通过 API（curl）

后端独立运行在 `:8000`，亦可经前端 `:5173` 的 vite proxy 访问。以下示例直接打后端：

```bash
# 健康检查 + LLM 状态
curl http://localhost:8000/api/healthz
curl http://localhost:8000/api/llm/status

# 获取论文列表（前 100 篇）
curl http://localhost:8000/api/papers

# 抓取论文（POST，JSON body：query 为 arXiv 检索式，keywords 过滤，max_results 数量）
curl -X POST http://localhost:8000/api/papers/fetch \
  -H "Content-Type: application/json" \
  -d '{"query":"cat:cs.CV","keywords":["diffusion","segmentation"],"max_results":10}'

# 为论文生成 BibTeX（需先有 paper_id）
curl -X POST http://localhost:8000/api/papers/<PAPER_ID>/bibtex

# 创建任务
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"复现 PaperX","priority":"high","status":"todo"}'

# 创建笔记
curl -X POST http://localhost:8000/api/notes \
  -H "Content-Type: application/json" \
  -d '{"title":"阅读笔记","content":"# 摘要\n...","type":"summary"}'

# 全局搜索（跨论文/任务/项目/笔记/实验）
curl "http://localhost:8000/api/search?q=transformer"

# AI 对话（SSE 流式）；rag_enabled=true 时自动检索已索引文档并标注引用
curl -N -X POST http://localhost:8000/api/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"message":"帮我抓取关于 diffusion 的论文","rag_enabled":true}'

# Multi-Agent 后台运行（返回 run_id，再轮询 /stream 拿进度）
curl -X POST http://localhost:8000/api/agent/runs \
  -H "Content-Type: application/json" \
  -d '{"requirement":"做一个待办事项 Web 应用"}'
# 取进度（SSE 流式）：
curl -N "http://localhost:8000/api/agent/runs/<RUN_ID>/stream"
# 查看某次运行的「可重放日志」（每轮模型实际看到的消息序列）：
curl "http://localhost:8000/api/agent/runs/<RUN_ID>/replay"
# 处理待审批工具（approval_id 来自 SSE 的 tool_approval 事件或 GET /approvals）：
curl -X POST "http://localhost:8000/api/agent/runs/<RUN_ID>/approvals/<APPROVAL_ID>" \
  -H "Content-Type: application/json" \
  -d '{"approved":true}'

# RAG：列出索引源 / 触发索引 / 问答
curl "http://localhost:8000/api/rag/sources"
curl -X POST http://localhost:8000/api/rag/index \
  -H "Content-Type: application/json" \
  -d '{"path":"D:/docs/my-papers","name":"我的文献库","recursive":true}'
curl -X POST http://localhost:8000/api/rag/query \
  -H "Content-Type: application/json" \
  -d '{"question":"这篇论文的核心方法是什么？","topK":5}'

# Cron：创建定时 arXiv 抓取任务（每周一 09:00；jobType 支持 command/agent_run/arxiv_fetch）
curl -X POST http://localhost:8000/api/cron/jobs \
  -H "Content-Type: application/json" \
  -d '{"name":"每周论文","schedule":"0 9 * * 1","jobType":"arxiv_fetch","payload":{"query":"cat:cs.CV","keywords":["diffusion"],"max":10,"days":1},"enabled":true}'
# 列出任务 / 手动触发 / 查看执行历史
curl "http://localhost:8000/api/cron/jobs"
curl -X POST "http://localhost:8000/api/cron/jobs/<JOB_ID>/run"
curl "http://localhost:8000/api/cron/jobs/<JOB_ID>/history"
```

> 说明：遗留的 `/api/agent/run`（一次性 SSE）已删除，统一走 `/api/agent/runs` 后台模式（落库即返、可取消、可审批、可跨页面接收完成提醒）。

### C. 直接调用 Python 脚本

```bash
# 抓取最近 1 天的 cs.CV 论文（最多 10 篇，不下载 PDF）
python scripts/fetch_arxiv.py fetch --max 10 --days 1

# 带关键词抓取并自动下载 PDF
python scripts/fetch_arxiv.py fetch --keywords "vision transformer" --max 20 --download

# 列出已存论文（前 50 篇）
python scripts/fetch_arxiv.py list --limit 50

# AI 总结单篇论文（需配置 LLM）
python scripts/summarize_paper.py <arxiv_id>
```

> 脚本通过环境变量 `DATA_DIR` 定位数据库；不设置时默认使用 `<项目根>/data`。后端在启动时会自动注入该变量。

---

## 📁 项目结构

```
ai-research-os/
├── frontend/                  # React + TypeScript 前端
│   ├── src/
│   │   ├── hubs/              # 各功能模块页面（Hub），hook/组件按 Hub 内聚
│   │   ├── components/        # 通用 / 布局 / UI 组件
│   │   ├── stores/            # Zustand 状态管理
│   │   ├── services/          # 前端 API 客户端（单点注入 X-Space-Key）
│   │   ├── config/            # 导航 manifest（navGroups / toolCommands，单一数据源）
│   │   ├── hooks/             # 少量跨 Hub 公共 hooks（大多内聚在各 Hub 内）
│   │   ├── types/             # 类型定义
│   │   └── utils/             # 工具函数
│   ├── vite.config.ts         # 含 /api proxy（开发态转发到后端 :8000）
│   └── package.json
├── backend/                   # 独立 FastAPI 后端
│   ├── server/
│   │   ├── main.py            # FastAPI app 入口（CORS / 路由装配 / 静态托管 / cron 调度启动）
│   │   ├── config.py          # 配置单例（LLM_* / DB_PATH / CORS / DATA_DIR）
│   │   ├── llm.py            # urllib 实现的 OpenAI 兼容 LLM 客户端（含 embeddings，零新依赖）
│   │   ├── db.py             # 进程内引导 database.py + init_db()
│   │   ├── deps.py           # get_space_id 空间隔离依赖
│   │   ├── errors.py         # 统一异常 / SSE 工具
│   │   ├── context.py        # 上下文管理（token 估算 / LLM 摘要 / compact_messages）
│   │   ├── tool_registry.py  # 工具注册表 + 审批策略内核（safe / sensitive / dangerous）
│   │   ├── tools/            # 插件化内置工具（@register_tool，自动发现；含 code_exec 沙箱）
│   │   ├── agent_runner.py   # 后台非阻塞 Agent 运行器（审批等待 + 可重放日志落库）
│   │   ├── cron_scheduler.py # 自研零依赖 Cron 调度器（daemon 线程 + DB 乐观锁防重）
│   │   ├── rag_service.py    # RAG 文档检索（discover/extract/chunk/embed/retrieve/answer）
│   │   ├── rag_runner.py     # RAG 后台索引
│   │   └── routers/          # 各 Hub 路由（tasks/papers/.../agent/chat/rag/cron）
│   ├── skills/               # Agent Skills（零依赖 SKILL.md 约定）
│   ├── requirements.txt       # 后端 Python 依赖（不含 openai）
│   └── .env.example          # LLM / DB / CORS / Agent / web_search 配置示例
├── scripts/                   # Python 后端脚本（业务逻辑 + QA 回归）
│   ├── database.py            # SQLite 数据模型（标准库，aiosqlite 异步）
│   ├── fetch_arxiv.py         # arXiv 抓取
│   ├── summarize_paper.py     # AI 论文总结
│   ├── agent_service.py       # Multi-Agent 服务（角色化管线）
│   ├── chat_agent_stream.py   # 聊天 / 工具调用
│   ├── rag_service.py         # RAG 检索服务（与 server 内同源）
│   ├── swanlab_*.py           # SwanLab 集成
│   ├── formula_service.py     # 公式 OCR
│   ├── citation_service.py    # 引用检索
│   ├── obsidian_service.py    # Obsidian 集成
│   └── qa_verify_*.py         # 回归验证脚本（space/agent/rag/chat 等，见「贡献指南」）
├── data/                      # 数据目录（SQLite / PDF / 导出，已 gitignore）
├── docs/                      # 架构与设计文档（见 docs/README.md 索引）
├── .archive/                  # 已归档的旧/过时文档（gitignored，确认无用后可整目录删）
├── AGENTS.md                  # 项目与开发规范（给 AI 协作者）
├── CHANGELOG.md               # 版本与里程碑变更记录
├── start.ps1 / start.sh       # 一键启动脚本（Windows / macOS / Linux）
└── .airos-data-dir            # （可选）数据目录指针，首行即路径
```

---

## ⚙️ 配置说明

后端通过环境变量或项目根 `.env` 配置（`backend/.env.example` 提供完整样例）：

### LLM 与服务

| 变量 | 默认 | 说明 |
|------|------|------|
| `LLM_BASE_URL` | `（空）` | OpenAI 兼容 LLM 基址，需在设置页 / `.env` 填写（本身含 `/v1`） |
| `LLM_HTTP_PATH` | `/chat/completions` | 聊天补全路径；最终 endpoint = `{BASE_URL}{LLM_HTTP_PATH}` |
| `LLM_API_KEY` | `（空）` | Bearer Token |
| `LLM_MODEL` | `（空）` | 模型名，可在设置页从接口读取可用模型 |
| `LLM_TEMPERATURE` | `0.7` | 采样温度 |
| `LLM_MAX_TOKENS` | `4000` | 最大生成 token |
| `LLM_TIMEOUT` | `120` | 请求超时（秒） |
| `DB_PATH` | `<DATA_DIR>/ai_research_os.db` | SQLite 路径 |
| `DATA_DIR` | `<项目根>/data` | 数据目录 |
| `APP_HOST` / `APP_PORT` | `0.0.0.0` / `8000` | 后端监听 |
| `CORS_ORIGINS` | `*` | 允许的前端来源（逗号分隔，生产建议收敛） |

### Agent 工程（v0.3）

| 变量 | 默认 | 说明 |
|------|------|------|
| `AGENT_APPROVAL_MODE` | `auto` | `auto`（敏感工具直接执行，危险工具拒绝）/ `manual`（敏感工具等审批）/ `strict`（敏感与危险均等审批） |
| `AGENT_REQUIRE_APPROVAL_TOOLS` | `（空）` | 逗号分隔的工具名，强制这些工具即使 auto 也要审批（如 `create_note,create_task`） |
| `AGENT_APPROVAL_TIMEOUT` | `300` | 审批等待超时（秒），超时按拒绝处理 |
| `AGENT_CONTEXT_TOKEN_LIMIT` | `24000` | 上下文预算，超限后把早期历史 LLM 压缩为摘要 |
| `AGENT_CONTEXT_KEEP_LAST` | `6` | 压缩时保留最近的消息条数 |
| `AGENT_MAX_TOOL_ROUNDS` | `8` | 单角色最大工具轮数（硬上限） |

### 集成与调度

| 变量 | 默认 | 说明 |
|------|------|------|
| `WEB_SEARCH_PROVIDER` | `bocha` | Agent 联网搜索：`bocha`（博查，国内直连）/ `wikipedia`（零密钥降级） |
| `BOCHA_API_KEY` | `（空）` | 博查搜索 API Key（bochaai.com 注册，含免费额度） |
| `CRON_SCAN_INTERVAL` | `60` | Cron 调度器扫描间隔（秒） |
| `CRON_SUBPROCESS_TIMEOUT` | `（空）` | command 型 Cron 任务子进程超时（秒） |

- **LLM 可配置化**：不依赖 `openai` SDK，改用 `backend/server/llm.py` 中基于 `urllib` 的客户端，可对接任意 OpenAI 兼容端点；`/v1/embeddings` 同时用于 RAG 索引。连接状态见 `/api/llm/status`。
- **数据库路径**：默认 `data/ai_research_os.db`，可通过 `DB_PATH` / `DATA_DIR` 覆盖；数据库以 WAL 模式打开，支持多 worker 并发。
- **前端端口**：`frontend/vite.config.ts` 中 `server.port`（默认 5173），其 `server.proxy['/api']` 转发到 `VITE_API_TARGET`（默认 `http://localhost:8000`；`start.ps1` 会根据 `-ApiPort` 自动设置）。
- **SwanLab**：在 *研发实验* 或调用 `/api/swanlab/config` 填写 API Key。
- **Cron 定时任务**：通过 `/api/cron/jobs` 管理（或前端「定时任务」工具页），配置与执行历史存入数据库（`cron_jobs` / `cron_run_history` 表）。

---

## 🛠️ 开发命令

```bash
# 前端
cd frontend
npm run dev       # 启动开发服务器（/api 经 proxy 转发到后端 :8000）
npm run build     # 类型检查 + 生产构建（输出 dist/，由后端静态托管）
npm run preview   # 预览生产构建
npm run lint      # ESLint 检查（--max-warnings 0，零警告通过）

# 后端
python -m uvicorn backend.server.main:app --port 8000 --workers 4   # 启动后端（多 worker）
python -m py_compile backend/server/**/*.py                         # 语法检查

# 回归验证（QA 脚本，改动后跑对应项；均在 managed/venv 环境运行）
python scripts/qa_verify_space.py                # 空间隔离 26 项
python scripts/qa_verify_agent_harness.py        # Agent 工程能力 61 项（审批/重放/上下文/插件化）
python scripts/qa_verify_agent_runner.py         # 后台 runner 19 项
python scripts/qa_verify_rag.py                  # RAG 检索 7 项
python scripts/qa_verify_chat_rag.py             # Chat 接地式 RAG 2 项
python scripts/qa_verify_chat_regenerate_edit.py # 聊天重生成/编辑
python scripts/qa_verify_chat_branching.py       # 会话分支
python scripts/qa_verify_conversation_id.py      # 会话 ID 一致性
python scripts/qa_verify_init_race.py            # 初始化竞态
```

Python 脚本无需构建，直接 `python scripts/xxx.py` 运行。

---

## 🤝 贡献指南

欢迎 Issue 与 PR！

### 提交流程

1. **Fork** 本仓库并克隆到本地。
2. 从 `main` 新建分支：
   - 功能：`feat/简短描述`（如 `feat/paper-batch-export`）
   - 修复：`fix/简短描述`
   - 文档：`docs/简短描述`
3. 在分支上开发，**提交前必须通过下方「验证清单」**。
4. 提交信息遵循 **Conventional Commits**：
   ```
   feat(paper): 支持按标签批量导出 BibTeX
   fix(chat): 修复流式响应中断后状态未复位
   docs(readme): 补充安装与使用示例
   ```
5. 推送分支并发起 **Pull Request**，在描述中说明：动机、改动点、测试方式。
6. 至少 1 名维护者 Review 通过后方可合并。

### 验证清单（提交前逐项确认）

```bash
# 前端：lint 零警告 + 类型检查 + 构建通过
cd frontend
npm run lint && npm run build

# 后端：语法检查 + 相关 QA 回归（按改动面选择）
python -m py_compile backend/server/**/*.py
python scripts/qa_verify_space.py            # 动了数据层 / 路由必跑
python scripts/qa_verify_agent_harness.py    # 动了 Agent / 工具 / 审批必跑
# 其余 qa_verify_*.py 按改动面补跑（见「开发命令」）
```

> 项目无 git 仓库 / 无单测框架（当前由维护者本地维护），QA 脚本即事实上的回归测试；新增功能请同步补充对应 `qa_verify_*.py`。

### 代码规范

- **前端**
  - TypeScript 开启严格模式；禁止 `any` 滥用。
  - 组件文件 `PascalCase`（如 `PaperList.tsx`），工具函数 `camelCase`。
  - 类型集中放 `src/types/`，跨 Hub 状态用 Zustand（按 Hub 拆分 store）。
  - **新增页面/能力的归属判断**：有独立数据模型 → 才考虑一级导航（`src/config/navigation.ts` 的 `navGroups`）；否则 → 作为工具命令（`toolCommands`）暴露给 Cmd+K，并嵌入所属业务域。导航 manifest 是单一数据源，侧边栏无硬编码。
  - 提交前通过 ESLint（`--max-warnings 0`）。
- **后端（Python）**
  - 遵循 PEP 8；优先使用标准库，新增第三方依赖需同步更新 `backend/requirements.txt` 与 README 安装步骤。
  - **禁止 `openai` SDK**：LLM 调用一律走 `backend/server/llm.py`。
  - 数据库操作统一走 `scripts/database.py`，不要直接写 SQL 散落在各脚本。
  - **空间隔离**：新增数据表/路由必须加 `space_id` 列并通过 `Depends(get_space_id)` 过滤；系统级接口可豁免。
  - **更新语义**：写操作返回 `rowcount > 0`，不要跨空间返回 True。
  - **新增工具 = 新模块**：用 `@register_tool` 装饰器写在 `backend/server/tools/<name>.py`（自动发现），不要在 Agent 主循环里硬编码工具分支；策略标注 `safe`（只读）/ `sensitive`（写库）/ `dangerous`（不可逆）。
  - 模块导入用正规包导入（`from . import x` / `from scripts import database`），**无 `sys.path` hack**。
  - 脚本入口采用 `python scripts/xxx.py <command> [--options]` 风格，输出 JSON 供后端解析。
- **提交**
  - 一个大功能拆成多个小 PR 更易 Review。
  - 不提交 `data/`、`node_modules/`、`*.db`、`.env`、`credentials/` 等（已在 `.gitignore`）。

### Issue 指南

- Bug：附复现步骤、环境（Node/Python 版本）、截图或日志。
- 新功能：描述使用场景与预期行为。

---

## 🔧 故障排查

| 现象 | 可能原因 | 解决 |
|------|----------|------|
| 前端「LLM Offline」/ `/api/llm/status` 显示 reachable=false | 未配置 LLM 端点 / 服务未启动 | 检查 `.env` 的 `LLM_BASE_URL`/`LLM_API_KEY`；启动兼容 LLM 端点；`curl /api/llm/status` 验证 |
| `/api/*` 返回 404 | 前端 proxy 未指向后端 / 后端未启动 | 确认后端 `:8000` 已起；确认 `vite.config.ts` 的 `server.proxy['/api'].target` 指向 `VITE_API_TARGET` |
| `/api/*` 返回 500 | Python 后端异常 | 查看 `uvicorn` 进程日志；确认 `pip install -r backend/requirements.txt` 已完成 |
| AI 总结失败降级为模板 | LLM 端点不可达 / 模型名错误 | `curl /api/llm/status`；检查 `LLM_MODEL` 与端点是否支持 `{BASE_URL}/chat/completions` |
| RAG 索引失败 / 回答无引用 | LLM 不支持 `/v1/embeddings` 或索引未建 | 确认在设置页「RAG 文档检索」录入并触发索引；确认 `rag_enabled=true` 且勾选了来源；不支持 embedding 时后端会自动降级关键词检索 |
| Agent 卡在「等待审批」 | 审批模式为 manual/strict 或工具被 `AGENT_REQUIRE_APPROVAL_TOOLS` 强制 | 在前端审批卡片 / 运行历史「工具审批」tab 处理；或调 `AGENT_APPROVAL_MODE=auto`；超时（默认 300s）自动按拒绝处理 |
| Cron 任务没触发 | 表达式写错 / 调度器未启动 / 多 worker 抢锁 | 检查表达式（5 字段 cron 或 daily/weekly/hourly 快捷词）；`curl /api/cron/jobs` 看 enabled 与 next_run；查看执行历史 `/api/cron/jobs/{id}/history` |
| 实验拉取失败 | 未配置 SwanLab Key | 在研发实验 / 设置中填写 API Key |
| 前端依赖装不上 | Node 版本过低 | 升级到 Node ≥ 18 |
| 数据库偶尔写入失败（busy） | 多进程/多设备并发写 | 确保同一时刻仅一个进程写库；见「数据备份与多设备同步」铁律 |

---

## 📄 文档索引

除本文外，更深入的设计与实现文档集中在 [`docs/`](./docs/README.md)：

- **SYSTEM-DESIGN.md** — 一页式综合设计（分层架构图、核心模块、四条核心数据流、关键决策）
- **ARCHITECTURE.md** — 系统定位、进程模型、分层、请求生命周期、关键架构决策
- **DATA-MODEL.md** — SQLite 数据模型、space-key 隔离、20 张表结构、更新语义
- **API.md** — 全部 `/api/*` 路由、SSE/NDJSON 帧格式、curl 速查
- **AGENT-LLM.md** — LLM 客户端、Chat ReAct 循环、角色化 Agent 管线、Skills 约定
- **FRONTEND.md** — 前端技术栈、路由、状态管理、设计系统
- **OPERATIONS.md** — 启动、配置、多人内网、备份、故障排查、验收脚本
- **TECH-DEBT.md** — 已知技术债与重复实现清单

---

## 📄 许可证

本项目当前以内部 / 研究用途为主，许可证待定。如需商用或二次分发，请联系维护者。

---

**最后更新**：2026-08-24 · 基于代码实况（v0.3 Agent 工程能力 / Cron 调度 / RAG 检索 / 导航 manifest）同步 README
