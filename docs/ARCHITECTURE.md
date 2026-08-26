# 系统架构

> 本文描述 AI-Research-OS **当前代码的真实形态**（核对日期：2026-08-26），不含未实现的规划。
> 配套文档：[API 参考](./API.md) · [数据模型](./DATA-MODEL.md) · [前端架构](./FRONTEND.md) · [LLM 与 Agent](./AGENT-LLM.md) · [部署运维](./OPERATIONS.md) · [技术债](./TECH-DEBT.md)

---

## 1. 系统定位

面向研究生的本地优先（local-first）科研工作台。11 个功能中心（Hub）覆盖论文、任务、项目、笔记、实验、公式、引用、对话与 Agent 运行，全部数据落在本机 SQLite + 文件系统，不依赖任何云服务。LLM 能力可插拔：不配置 LLM 时，所有 CRUD 与检索功能照常工作。

三条硬约束贯穿整个设计：

| 约束 | 体现 |
|---|---|
| **本地优先** | 单文件 SQLite（WAL）+ `data/` 目录，可整体拷贝/同步盘/备份包迁移 |
| **零重依赖** | 后端 9 个直接 pip 依赖，LLM 客户端用标准库 urllib 手写，前端 shadcn 组件源码内置 |
| **不登录的多人可用** | space-key 软隔离：一个 HTTP 头分空间，无账号体系、无密码、无 session |

---

## 2. 进程模型

```
┌──────────────────────────────────────────────────────────────────┐
│  浏览器                                                           │
│  React 18 SPA  ──  fetch('/api/...')  +  X-Space-Key 头           │
└───────────────┬──────────────────────────────────────────────────┘
                │
    开发态       │ :5173  Vite Dev Server（仅做静态服务 + /api 反向代理）
    生产态       │ :8000  uvicorn 直接托管 frontend/dist（StaticFiles，html=True）
                ▼
┌──────────────────────────────────────────────────────────────────┐
│  uvicorn  --workers N      (N = min(CPU, 8)，无 --reload)          │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ FastAPI  backend.server.main:app                            │  │
│  │  · CORSMiddleware（唯一中间件）                              │  │
│  │  · 20 个 APIRouter，前缀写在各 router 内                     │  │
│  │  · Depends(get_space_id) —— 处理器级空间解析，非中间件        │  │
│  │  · 统一异常处理器 → {success,error,message}                  │  │
│  └───────┬──────────────────────────┬──────────────┬───────────┘  │
│          │ 进程内 import             │ subprocess   │ 守护线程     │
│          ▼                          ▼              ▼              │
│   scripts/database.py         scripts/*.py    agent_runner        │
│   （aiosqlite 异步）        （外部集成 CLI）  （后台 Agent run）    │
└──────────┬────────────────────────┬───────────────┬──────────────┘
           ▼                        ▼               ▼
   data/ai_research_os.db     外部 API          LLM 端点
   （WAL，26 张表）        arXiv/Crossref/     （OpenAI 兼容）
                          SwanLab/SimpleTex
```

**为什么无 `--reload`**：多 worker 与 reload 互斥；WAL 模式下多进程共享同一 DB 文件是安全的，Agent 运行状态也全部落库，因此多 worker 之间无需共享内存。

---

## 3. 分层结构

### 3.1 后端 `backend/`

```
backend/
├── agent_roles.json          Agent 角色管线配置（数组顺序 = 执行顺序）
├── requirements.txt          8 个依赖，无 openai SDK
├── scripts/                 顶层工具包（database / fetch_arxiv / chat_agent_stream / summarize_paper …）
├── server/
│   ├── __init__.py           包说明文档（已无 sys.path 注入 hack）
│   ├── agent_service.py      角色化多 Agent 管线（与 server 同包，正规导入）
│   ├── main.py               FastAPI 入口：lifespan / CORS / 挂载 router / SPA 托管
│   ├── config.py             pydantic-settings 配置单例 + .env 加载 + DATA_DIR 副作用
│   ├── deps.py               space-key 解析依赖（normalize_space_key / get_space_id）
│   ├── db.py                 数据层引导壳，import scripts/database.py 并再导出
│   ├── llm.py                OpenAI 兼容 LLM 客户端（urllib 手写，含 SSE 与 function calling）
│   ├── agent_runner.py       后台非阻塞 Agent runner（线程 + 自建事件循环）
│   ├── skills_bridge.py      SKILL.md 扫描与调用（Agent Skills 开放标准）
│   ├── memory.py             按空间的持久记忆（data/memory/<space_id>.md）
│   ├── helpers.py            run_script()：subprocess 调 scripts/*.py 并解析 stdout JSON
│   ├── errors.py             统一错误体 + APIError + SSE 辅助
│   ├── health.py             /api/healthz 与 /api/llm/status
│   ├── schemas.py            跨 router 共享的 Pydantic 模型
│   └── routers/              21 个 router，共 113 条 /api 路由
└── skills/                   目录式技能：<name>/SKILL.md (+ scripts/)
```

### 3.2 脚本层 `scripts/`

同时承担两个角色：**被后端进程内 import 的库** 和 **被 subprocess 调用的 CLI**。

| 文件 | 调用方式 | 说明 |
|---|---|---|
| `database.py`（2137 行） | 进程内 import | 数据层核心，aiosqlite，20 表 DDL + 全部 CRUD |
| `chat_agent_stream.py` | 进程内 import | 导出 `SYSTEM_PROMPT` / `TOOLS` / `execute_tool`，被 chat 与 skills 路由复用 |
| `fetch_arxiv.py` | 进程内 import | arXiv 搜索与 PDF 下载 |
| `summarize_paper.py` | 进程内 import | 总结 prompt 构造 + LLM 不可用时的降级摘要 |
| `swanlab_api.py` / `swanlab_integration.py` | subprocess | SwanLab 实验数据拉取 |
| `citation_service.py` | subprocess | Crossref 检索 + 6 种引用格式生成 |
| `obsidian_service.py` | subprocess | Obsidian vault 扫描（**唯一仍用同步 sqlite3 的数据访问点**） |
| `formula_service.py` | subprocess | SimpleTex 公式 OCR + 历史记录 |
| `qa_verify_space.py` / `qa_verify_agent_runner.py` | 手动执行 | 独立 QA 验收脚本 |

**进程内 vs subprocess 的分界**：核心数据链路走进程内 import（性能 + 事务一致性）；外部集成保留 subprocess（隔离第三方 SDK 风险、崩溃不拖垮主进程），空间上下文通过 `SPACE_ID` 环境变量传入。

### 3.3 前端 `frontend/src/`

11 个 Hub + 全局挂件，详见 [FRONTEND.md](./FRONTEND.md)。关键点：所有 `/api` 请求经 `services/apiMonitor.ts` 对 `window.fetch` 的单点 patch 注入 `X-Space-Key`，业务代码无需关心空间。

---

## 4. 请求生命周期

### 4.1 普通 CRUD

```
fetch('/api/papers')
  → apiMonitor patch 注入 X-Space-Key: <归一化 key>
  → (dev) Vite proxy → (prod) uvicorn
  → FastAPI 路由匹配
  → Depends(get_space_id)：trim + lower，长度 < 4 → 400 SPACE_REQUIRED
  → router 调 database.get_all_papers(space_id=...)
  → get_db() 新建一条 aiosqlite 连接（PRAGMA WAL/NORMAL/busy_timeout=5000/foreign_keys=ON）
  → WHERE space_id = ? 过滤
  → *_to_dict() 转 camelCase 并 json.loads JSON 列
  → 关闭连接，返回 JSON
```

每个请求独立建连、用完即关，绝不跨协程共享连接——这是多 worker 下不出现 `database is locked` 的前提。

### 4.2 Chat 流式对话（ReAct 循环）

```
POST /api/chat/completions/stream
  → 载入历史 + 注入该空间的持久记忆 + 上下文超限时 LLM 压缩历史
  → stream_llm(messages, tools=TOOLS)     ← 原生 function calling
  → 边收边输出 SSE：data: {"type":"text"|"tool_start"|"tool_result"|"context"|"rag_sources"|"error"}
  → 若模型返回 tool_calls：execute_tool() 执行 → 结果回填 messages → 再次进入循环
  → 结束输出 [DONE]
```

这条链路当前是标准 **SSE**（`text/event-stream` + `data:` 帧）；前端仍用 `getReader()` 手工解析，以兼容历史无前缀格式并接入 AbortSignal。

### 4.3 Agent 后台运行（非阻塞）

```
POST /api/agent/runs
  → submit_run()：落库 agent_runs + 注册 threading.Event + 起守护线程 → 立即返回 runId
  ↓（后台线程内 asyncio.new_event_loop()）
  → 按 agent_roles.json 顺序逐角色执行，每一帧事件立刻写入 agent_run_events
  ↓
GET /api/agent/runs/{id}/stream
  → 标准 SSE，但推送源是 DB 轮询（0.6s 游标增量），因此跨 worker 天然可见
POST /api/agent/runs/{id}/cancel
  → 内存 Event（同 worker 即时）+ DB status（跨 worker，每阶段前复查）双层取消
```

`run_full_workflow` 是同步阻塞生成器（内部 LLM 走同步 urllib），直接放进协程会卡死事件循环——这正是 runner 存在的理由。旧的 `POST /api/agent/run`（SSE 直跑）仍保留向后兼容，但会阻塞该 worker 的协程。

---

## 5. 关键架构决策

### 5.1 零 SDK 的 LLM 客户端

`backend/server/llm.py` 全部用标准库 `urllib.request` 实现，包含手写 SSE 解析和 function-calling 分片累积（按 `index` 累积 `id`/`name`/`arguments`）。`requirements.txt` 里明确注释「不需要 openai SDK」。收益是依赖极轻、离线可装；代价是需要自己处理流式边界与重试。

**URL 拼接采用 OpenAI SDK 风格**：Base URL 自带 `/v1`，`LLM_HTTP_PATH` 默认 `/chat/completions`，最终 endpoint = `{base}/chat/completions`。`config.py` 有一处兼容补丁：当 base 以 `/v1` 结尾且 path 以 `/v1/` 开头时自动剥掉重复前缀。

### 5.2 space-key 软隔离

- 身份 = 用户主动填写的稳定口令，`trim + lower` 后**直接作为 `space_id`，不做 hash**，最短 4 字符，允许中文。
- 隔离手段是「每张表一个 `space_id` 列 + 单列索引 + `WHERE` 过滤」，**不做 JOIN**；子表反范式写入父空间。
- `X-Space-Key` 是**处理器级依赖**而非中间件，因此可精确豁免系统级接口。
- 豁免范围：`settings` / `healthz` / `llm/status` / `backup` / `skills` / `swanlab` / `citation`——这些是全局配置或全局能力。
- 特例：`chat` 路由不强制，缺头时静默回落 `__default__`（不返回 400）。
- 文件系统按 `data/<module>/<space_id>/` 归档。
- 存量数据统一迁移到 `__default__`。

### 5.3 Agent Skills 开放标准

`backend/skills/<name>/SKILL.md`（frontmatter + 正文）即技能本体，与 Claude Code / Codex 生态目录约定兼容，可直接互换。分两类：`instruction`（纯提示词工作流）与 `tool`（声明 `command` 可执行）。安全边界：**命令只能来自受信任的 SKILL.md，模型只能提供参数，永远无法指定执行什么命令**。

### 5.4 已废弃的历史路径

- **OpenClaw**：早期 LLM 提供方，已于 2026-07-28 全量移除（代码 / 配置 / 文档）。现改为任意 OpenAI 兼容端点，界面可配。
- **Vite 插件式后端**：早期在 `vite.config.ts` 的 `configureServer` 里 spawn Python（约 1150 行），已迁往独立 FastAPI。遗留物 `frontend/api-server.js`、`scripts/db_api.py`、`scripts/workflow_engine.py` 均为死代码，见 [TECH-DEBT.md](./TECH-DEBT.md)。

---

## 6. 数据流与外部依赖

| 外部服务 | 用途 | 调用方 | 缺失时的行为 |
|---|---|---|---|
| OpenAI 兼容 LLM | 对话 / 论文总结 / Agent / 记忆提炼 | `llm.py`（进程内） | CRUD 不受影响；总结降级为规则摘要；Chat/Agent 报错提示 |
| arXiv Atom API | 论文抓取 | `fetch_arxiv.py`（进程内） | 抓取失败，已有数据可用 |
| Crossref | 引用元数据检索 | `citation_service.py`（subprocess） | 引用生成不可用 |
| SwanLab | 实验数据同步 | `swanlab_api.py`（subprocess） | 实验 Hub 只读本地缓存 |
| SimpleTex | 公式 OCR | `formula_service.py`（subprocess） | 公式识别不可用 |
| Google Fonts / cdnjs | 字体、PDF worker | 浏览器直连 | 字体回退系统字体；**PDF 预览失效**（内网环境需自托管） |

---

## 7. 部署形态

| 形态 | 命令 | 说明 |
|---|---|---|
| 开发（前后端分离） | `.\start.ps1` / `./start.sh` | 后端 :8000 + Vite :5173，`/api` 反代 |
| 仅后端 | `.\start.ps1 -SkipFrontend` | 调试 API 用 |
| 生产（单进程托管） | `npm run build` 后 `uvicorn backend.server.main:app --workers N` | uvicorn 同时提供 `/api` 与 SPA，无需 nginx |
| 内网多人 | 同上 + `APP_HOST=0.0.0.0` + 各自填不同 space key | 详见 [OPERATIONS.md](./OPERATIONS.md) |

详细参数、环境变量与排障见 [OPERATIONS.md](./OPERATIONS.md)。
