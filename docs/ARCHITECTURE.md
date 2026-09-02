# 系统架构

> 核对日期：2026-09-02；事实数字以 `docs/_meta.json` 为准（当前 `hubs=12 / routers=22 / tables=31`）。
> 索引：[README](./README.md) · [DATA-MODEL](./DATA-MODEL.md) · [API](./API.md) · [AGENT-LLM](./AGENT-LLM.md) · [FRONTEND](./FRONTEND.md) · [OPERATIONS](./OPERATIONS.md)

## 1. 定位与硬约束

本地优先科研工作台，LLM 可插拔（不配时 CRUD/检索照常）。

| 约束 | 落地 |
|---|---|
| 本地优先 | SQLite WAL + `data/` 整体拷贝/备份包迁移 |
| 零重依赖 | `urllib` 手写 LLM 客户端（禁 `openai` SDK），前端 shadcn 源码内置 |
| 不登录多人可用 | `X-Space-Key` 软隔离，无账号/密码/session |

## 2. 进程与分层

```
浏览器 React SPA --fetch /api + X-Space-Key--> Vite :5173 --proxy--> FastAPI :8000 --import--> scripts/database.py
                                                              |-> subprocess: scripts/*.py
                                                              |-> 守护线程: agent_runner / development_runner / cron_scheduler
                                                              `-> SQLite WAL + 文件系统 / LLM / arXiv / Crossref / SwanLab
```

- `backend/server/main.py`：CORS → 异常处理 → 挂载 `routers`（22个，见 `_meta.json`）→ `lifespan: init_db + start_scheduler + start_development_runner` → 生产态托管 `frontend/dist`。
- `frontend/src/App.tsx`：12 个 Hub 全部 `React.lazy` 分割，`installApiMonitor()` 单点注入 `X-Space-Key`。
- `scripts/`：同时是**被 import 的库**（`database/chat_agent_stream/fetch_arxiv`）和**被 subprocess 调的 CLI**（`swanlab/citation/formula/obsidian`），后者经 `SPACE_ID` 环境变量透传空间。

**多 Worker**：`uvicorn --workers N` 无 `--reload`，状态全落库跨 Worker 可见，无共享内存。

## 3. 请求生命周期

**CRUD**：`fetch /api/papers` → `apiMonitor` 注入头 → `Depends(get_space_id)`（<4 → 400）→ `get_db()` 独立 `aiosqlite` 连接（`busy_timeout=5000 → WAL → NORMAL → foreign_keys=ON`，有限重试）→ `WHERE space_id=?` → `*_to_dict` 转 `camelCase`。

**Chat SSE**：`POST /api/chat/completions/stream` → 载入历史+记忆+RAG 预检索 → `context.compact_messages` 超限摘要 → `llm.stream_llm(tools)` ReAct 循环（`tool_start/tool_result/context/rag_sources`）→ `[DONE]`。前端 `chatGenerationManager` 单例保证切 Hub 不中断（前端级后台），`ChatPanel` 与 ChatHub 共享同一会话。

**Agent 后台**：`POST /api/agent/runs` → `submit_run` 落库+`threading.Event`+守护线程（`new_event_loop`）→ 按 DAG 拓扑/`maxConcurrency` 并发节点，`__approval_required/__replay` 内部事件，帧逐条落 `agent_run_events` → 前端 DB 轮询 SSE（`after_id` 游标，0.6s）→ 双层取消（内存 Event + DB `cancelled`）。

**研发 Runner**：`development_runner` 固定 `analysis→implementation→testing→review` 循环，模型只返完整文件 JSON，服务端 `safe_path` 校验+原子写入，验证命令白名单（`pytest/unittest` / `npm run <script>`），产物与 `awaiting_apply` 需显式 `apply`（带 `baseRevision/diffDigest` 校验）。

**Cron**：每 Worker 60s 扫描，单条 `UPDATE ... WHERE next_run=?` 原子领取（旧值作乐观锁），三类 `command/agent_run/arxiv_fetch` 共用 `dispatch_job`。

## 4. 关键决策

| 决策 | 理由 |
|---|---|
| `urllib` 而非 SDK | 零依赖、端点/鉴权/流式可控；`LLM_BASE_URL` 含 `/v1`，`LLM_HTTP_PATH=/chat/completions`，`{base}{path}` 拼接，`config.py` 自动去重 `/v1/v1` |
| 状态全落 SQLite | 多 Worker 可见/可取消/重启不丢；`UPDATE rowcount` 即锁 |
| 线程+自建 loop 跑 Agent | `run_role` 是同步生成器（同步 urllib），入协程会卡死事件循环 |
| `send()` 暂停而非回调 | 审批语义清晰：`yield __approval_required → gen.send(bool)` |
| 摘要而非截断 | 截断会切断 `assistant(tool_calls)→tool` 配对；`context.py` 选最近 `user` 边界切分 |
| `@register_tool` 自动发现 | `tools/` 目录 `pkgutil` 发现，`safe/sensitive/dangerous × auto/manual/strict` 随注册声明 |

## 5. 外部依赖（可插拔）

| 服务 | 调用方 | 缺失时 |
|---|---|---|
| LLM | `llm.py` | 总结降级 `fallback`，Chat/Agent 报错帧 |
| arXiv | `fetch_arxiv` | 抓取失败不影响已有数据 |
| Crossref/SwanLab/SimpleTex | subprocess | 对应 Hub 降级/只读缓存 |

## 6. 研发/团队

- 专家团队：`backend/agent_teams/*.json` 内置，`agent_teams.py` 校验 `schemaVersion=1` DAG（无环/可达/工具白名单），提交时快照 `teamSnapshot/inputContext`，`agent_run_nodes` 跟踪节点状态。
- 研发团队：`LabHub` 合并原 `software/experiment`（`/software→/lab` 重定向），隔离工作区 `data/dev_workspaces/<space>/<run>/`。
