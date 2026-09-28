# 系统架构

> 核对日期：2026-09-28；事实数字以 `docs/_meta.json` 为准（当前 `hubs=12 / routers=22 / tables=36`）。
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
浏览器 React SPA --fetch /api + X-Space-Key--> Vite :5173 --proxy--> FastAPI :8000 --import--> scripts/database.py（兼容门面）
                                                                                  `-> scripts/db/{core,migrations,repos}
                                                              |-> subprocess: scripts/*.py
                                                              |-> 守护线程: agent_runner / development_runner / cron_scheduler
                                                              `-> SQLite WAL + 文件系统 / LLM / arXiv / Crossref / SwanLab
```

- `backend/server/main.py`：CORS → 异常处理 → 挂载 `routers`（22个，见 `_meta.json`）→ `lifespan: init_db + start_scheduler + start_development_runner` → 生产态托管 `frontend/dist`。
- `backend/server/admin_access.py`：部署级管理边界；本机 loopback 免令牌，远程 settings/backup/SwanLab/Skills 请求必须通过 `X-Admin-Token`，与 space-key 软隔离职责分离。
- `frontend/src/App.tsx`：12 个 Hub 全部 `React.lazy` 分割；业务请求统一经过 `services/api.ts`。
- `scripts/`：同时是**被 import 的库**（`database/chat_agent_stream/fetch_arxiv`）和**被 subprocess 调的 CLI**（`swanlab/citation/formula/obsidian`），后者经 `SPACE_ID` 环境变量透传空间。
- `scripts/db/`：`core.py` 管理连接与事务，`migrations/` 用显式版本账本单向升级，`repos/` 按业务域承载 SQL；多 Worker 启动由迁移锁串行化。

**多 Worker**：`uvicorn --workers N` 无 `--reload`，状态全落库跨 Worker 可见，无共享内存。

## 3. 请求生命周期

**CRUD**：业务 service → `services/api.ts` 注入请求头并执行 `fetch /api/papers` → `Depends(get_space_id)`（<4 → 400）→ `get_db()` 独立 `aiosqlite` 连接（`busy_timeout=5000 → WAL → NORMAL → foreign_keys=ON`，有限重试）→ `WHERE space_id=?` → `*_to_dict` 转 `camelCase`。

**Chat SSE**：`POST /api/chat/completions/stream` → 载入历史+记忆+RAG 预检索 → `context.compact_messages` 超限摘要 → `llm.stream_llm(tools)` ReAct 循环（`tool_start/tool_result/context/rag_sources`）→ `[DONE]`。前端 `chatGenerationManager` 单例保证切 Hub 不中断（前端级后台），`ChatPanel` 与 ChatHub 共享同一会话。

**Agent 后台**：`POST /api/agent/runs` → `submit_run` 落库+`threading.Event`+守护线程（`new_event_loop`）→ 按 DAG 拓扑/`maxConcurrency` 并发节点，`__approval_required/__replay` 内部事件，帧逐条落 `agent_run_events` → 前端 DB 轮询 SSE（`after_id` 游标，0.6s）→ 双层取消（内存 Event + DB `cancelled`）。

**研发 Runner**：`development_runner` 固定 `analysis→implementation→testing→review` 循环，模型只返完整文件 JSON，服务端 `safe_path` 校验+原子写入，验证命令白名单（`pytest/unittest` / `npm run <script>`），产物与 `awaiting_apply` 需显式 `apply`（带 `baseRevision/diffDigest` 校验）。

**Cron**：每 Worker 60s 扫描，单条 `UPDATE ... WHERE next_run=?` 原子领取（旧值作乐观锁），三类 `command/agent_run/arxiv_fetch` 共用 `dispatch_job`。

**RAG 2.1**：local / paper / web 统一写入 `rag_index_jobs`；各 Worker 先竞争
`rag_worker_lease(index-writer)`，全局仅一个索引写者。local 重建写入新
`generation_id`，完成后单事务切换 `active_generation_id`，失败或取消时旧代仍可检索。
检索先从全量 FTS5 与 sqlite-vec 取候选；无 sqlite-vec 时按 rowid 分页扫描完整活动语料，
只保留有界 top-k heap，不再截断前 3000 条。嵌入由不可变 profile
（provider/model/revision/dims/normalization/query instruction）隔离，不兼容时只走 sparse。
`sqlite-vec` 是默认安装的本地轻量加速层，但不是正确性单点：启动脚本会实际加载扩展做冒烟检查，
运行时若扩展未就绪仍回退 FTS5 + 流式余弦全语料召回。

RAG 的 local 索引任务持久化固定 `generation_id`、阶段与检查点；进程重启后跳过已原子落库的文件，
并从未完成的 embedding 批次继续。后续扫描按文件大小、纳秒 mtime、全文哈希与切片器签名复用
旧代文档；切片优先尊重 Markdown 标题和段落边界，并按估算 token 预算控制大小。同一不可变
embedding profile 下以 `chunk_hash` 复用向量缓存，无变化重扫不会重新解析或向量化。

## 4. 关键决策

| 决策 | 理由 |
|---|---|
| `urllib` 而非 SDK | 零依赖、端点/鉴权/流式可控；`LLM_BASE_URL` 含 `/v1`，`LLM_HTTP_PATH=/chat/completions`，`{base}{path}` 拼接，`config.py` 自动去重 `/v1/v1` |
| 状态全落 SQLite | 多 Worker 可见/可取消/重启不丢；`UPDATE rowcount` 即锁 |
| 线程+自建 loop 跑 Agent | `run_role` 是同步生成器（同步 urllib），入协程会卡死事件循环 |
| `send()` 暂停而非回调 | 审批语义清晰：`yield __approval_required → gen.send(bool)` |
| 摘要而非截断 | 截断会切断 `assistant(tool_calls)→tool` 配对；`context.py` 选最近 `user` 边界切分 |
| `@register_tool` 自动发现 | `tools/` 目录 `pkgutil` 发现，`safe/sensitive/dangerous × auto/manual/strict` 随注册声明 |
| SQLite-vec 为派生索引 | `rag_chunks` 仍是真源；扩展缺失/未就绪时流式暴力召回，避免维护 FAISS 第二套持久状态 |
| 轻量显式迁移而非 ORM | SQLite 是唯一数据库；`schema_migrations` + 校验和 + 事务迁移满足审计/恢复需求，不引入 SQLAlchemy/Alembic |

## 5. 外部依赖（可插拔）

| 服务 | 调用方 | 缺失时 |
|---|---|---|
| LLM | `llm.py` | 总结降级 `fallback`，Chat/Agent 报错帧 |
| arXiv | `fetch_arxiv` | 抓取失败不影响已有数据 |
| Crossref/SwanLab/SimpleTex | subprocess | 对应 Hub 降级/只读缓存 |

## 6. 研发/团队

- 专家团队：`backend/agent_teams/*.json` 内置，`agent_teams.py` 校验 `schemaVersion=1` DAG（无环/可达/工具白名单），提交时快照 `teamSnapshot/inputContext`，`agent_run_nodes` 跟踪节点状态。
- 研发团队：`LabHub` 合并原 `software/experiment`（`/software→/lab` 重定向），隔离工作区 `data/dev_workspaces/<space>/<run>/`。
