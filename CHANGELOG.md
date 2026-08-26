# Changelog

本项目并非严格语义化版本发布，以下按**里程碑**记录关键架构与文档变更。版本号仅作阶段标记。

---

## [未发布] - 2026-08-26 · 正确性修复与文档同步

- 修复 `LLMClient._reachable()` 因定义丢失导致 `/api/llm/status` 与 `is_available()` 抛 `AttributeError`；新增无网络回归 `qa_verify_llm_status.py`。
- 修复旧 `cron_jobs.json` 迁移 SQL 的列数/占位符不一致（11 列误写 12 个值）。
- 修复聊天重新生成/编辑时删除尾部消息后未更新 `current_leaf_id`，导致当前分支读取为空。
- QA 去除对本机真实 LLM 和仓库根 Node 模块解析的偶然依赖；空间迁移、Agent runner、Chat-RAG、Markdown 用例改为确定性执行。
- 文档按代码实况同步为 21 个 Router、113 条 `/api` 路由、26 张业务表；Chat 流协议更正为 SSE。

---

## [v0.3] - 2026-08-21 · Agent 工程能力（对齐 DeepSeek Harness 四项差距）

对照 DeepSeek Harness（dsh）差距分析，落地四项工程能力：**工具审批 / 可重放日志 / 上下文管理 / 插件化**。

### 工具审批（P0，安全护栏）
- `backend/server/tool_registry.py`：`ToolSpec` + `@register_tool` 注册表；策略 `safe`（只读直通）/ `sensitive`（写库，manual/strict 等待审批）/ `dangerous`（不可逆，非 strict 一律拒绝 = fail-closed）。
- 审批模式环境变量 `AGENT_APPROVAL_MODE`（auto 默认 / manual / strict），`AGENT_REQUIRE_APPROVAL_TOOLS` 单工具强制覆盖，`AGENT_APPROVAL_TIMEOUT` 超时（默认 300s，超时按拒绝）。
- 生成器双向通信：`run_role` 遇敏感/危险工具 `yield {"type":"__approval_required",...}` 暂停，`gen.send(decision)` 回传决策（拒绝即 fail-closed）。
- 后台 runner 审批等待：`agent_tool_approvals` 表落 pending 行 + 异步轮询（跨 worker 可见），与取消机制同一哲学；SSE 事件 `tool_approval`（pending/approved/denied/timed_out/cancelled）。
- 前端：Agent 协作面板（`agent-workflow.tsx`）审批卡片「允许执行 / 拒绝」；`AgentRunsHub` 详情抽屉新增「工具审批」tab（待审批决策按钮 + 历史记录）；事件流展示审批状态。

### 可重放日志（P1，Model-visible ⟺ logged）
- `agent_replay_messages` 表：每轮「模型实际看到的消息序列」按 `(phase, round)` 落库（含 tool_calls / tool 回灌），`append_agent_replay` / `get_agent_replay`（按 phase, round, id 升序取回）。
- `run_role` 初始消息落 round 0，每工具轮落 round n；runner 消费 `__replay` 内部事件持久化。
- `GET /api/agent/runs/{id}/replay` + 前端「会话回放」tab：按角色/轮次分组渲染 system/user/assistant/tool 消息与工具调用。

### 上下文管理（P1，替代粗暴截断）
- `backend/server/context.py`：`estimate_tokens`（CJK≈1 token）+ `summarize_history`（LLM 摘要）+ `compact_messages(messages, limit, keep_last)`——超预算时把早期历史压缩为单条 system 摘要，切分点选在最近 user 边界，**保证不切断 assistant(tool_calls) 与 tool 结果配对**；找不到干净边界则跳过压缩。
- Chat 与 Agent 管线共用（`chat.py` 抽出，`agent_service` 集成 `AGENT_CONTEXT_TOKEN_LIMIT` / `AGENT_CONTEXT_KEEP_LAST`）；压缩时发 `context_compressed` 事件。
- `AGENT_MAX_TOOL_ROUNDS` 默认 3→8。

### 插件化（P2）
- `backend/server/tools/` 目录 + `pkgutil.iter_modules` 自动发现：新增工具只需写一个 `@register_tool` 模块，**无需改动 Agent 主循环**。
- 5 个内置工具从 `chat_agent_stream.py` 迁移为装饰器注册（fetch_papers/get_stats=safe，create_task/create_project/create_note=sensitive）；技能工具经 `get_tools()` 合并。
- `run_coro_sync` 跨上下文 DB 执行助手（检测 running loop，线程池提交，修复 Agent runner 线程内 `asyncio.run` 崩溃隐患）。

### 验证
- 新增 `scripts/qa_verify_agent_harness.py`（61 项，全部 PASS）：审批策略矩阵、生成器暂停/恢复、重放往返、上下文压缩、插件发现、HTTP 审批全链路（拒绝+批准+写库断言）。
- 前端 `tsc --noEmit` + `vite build` 通过。

---

## [v0.2] - 2026-07-30 · 文档重构 + 多人内网化

### 文档
- **基于代码实况全面重写文档**：原文档多为早期设计推测，与实现严重偏离，本次统一以代码为准。
- 新增 `docs/` 专门文档集：
  - `ARCHITECTURE.md` — 系统定位（本地优先 / 零重依赖 / 不登录多人可用）、进程模型、分层、请求生命周期、关键架构决策。
  - `DATA-MODEL.md` — SQLite 数据模型、space-key 软隔离、20 张表结构、更新语义。
  - `API.md` — 全部 `/api/*` 路由（93 条）、SSE/NDJSON 帧格式、curl 速查（修正旧 README 的错误示例）。
  - `AGENT-LLM.md` — LLM 客户端、Chat ReAct 循环、角色化 Agent 管线、`agent_runner`、Skills 约定、模块导入约定（正规包导入）。
  - `FRONTEND.md` — 前端技术栈、路由、状态管理、设计系统。
  - `OPERATIONS.md` — 启动、配置、多人内网、备份、故障排查、验收脚本。
  - `TECH-DEBT.md` — 已知技术债与重复实现清单。
  - `README.md` — 文档索引。
- 归档过时/冗余文档至 `.archive/docs-legacy-20260730/`（非 git 仓库，先归档而非直接删）：`DESIGN.md`、`FEATURES.md`、`dev-log.md`、`docs/system_design.md`、`docs/design_space_isolation.md`、`docs/prd_space_isolation.md`、`docs/hub-split-plan.md`、`docs/obsidian-integration-design.md`、以及 `docs/*.svg` / `docs/*.mermaid`。
- 重写 `README.md` 与 `AGENTS.md`，与实现对齐（修正 API 示例、更新项目结构树、标注已实现状态、补充 space-key 与后台 Agent 说明）。

### 架构 / 功能（已实现，本次补文档）
- **space-key 软隔离**：内网多人共享部署，按空间密钥（trim+lower，不哈希）隔离数据，20 张表各加 `space_id` + 处理器级 `get_space_id` 依赖。
- **后台非阻塞 Agent 运行**：`/api/agent/runs` 落库即返 run_id，线程 + 自建事件循环跑管线，DB 轮询式 SSE（`/stream`）+ 双重取消（`/cancel`）。
- **前端完成提醒**：切走页面后后台 Agent 完成仍通过 `agentRunStore` + `agent-run-watcher` 弹 toast。

---

## 技术债偿还（2026-07-30）

基于 `docs/TECH-DEBT.md` 已偿还 4 项（含 2 项高风险）：
- **T1 mask_key 统一**：新建 `backend/server/utils.py:mask_key` 为唯一实现，`llm.py` / `settings.py` / `health.py` 统一调用，删除 `llm.py` 与 `settings.py` 中两套不一致实现。
- **T2 PDF worker 本地化**：`frontend/src/components/ui/pdf-viewer.tsx` 改为从 `pdfjs-dist/build/pdf.worker.min.mjs?url` 经 Vite 本地打包（并显式把 `pdfjs-dist@5.4.296` 加入 `package.json` 依赖），去掉对 `cdnjs.cloudflare.com` 的运行时依赖；`npm run build` 通过，worker 已打入 `dist/assets`。
- **T3 旧 Agent 端点标注 deprecated**：`routers/agent.py` 的 `/api/agent/run`、`/api/agent/collaborate` 加 DEPRECATED 注释并在响应头返回 `Deprecation: true`（端点已于 2026-07-31 确认无调用方后整体删除）；新前端走 `/api/agent/runs` 后台体系。
- **T5 死代码归档**：`scripts/db_api.py`、`scripts/workflow_engine.py`、`frontend/src/components/ui/tag-system.tsx`、`frontend/src/utils/performance.ts` 移入 `.archive/dead-code-20260730/`（保留原目录结构，归档前 grep 确认零外部引用）。

## 技术债偿还（2026-07-31）

延续上节，再偿还 3 项，并将 T3 旧端点彻底移除：
- **T3 旧 Agent 端点彻底删除**：用户确认无调用方后，`routers/agent.py` 的 `/api/agent/run`、`/api/agent/collaborate` 两个遗留一次性 SSE 端点整体删除（含仅服务它们的 `import agent_service`、`LLMUnavailableError`）；前端唯一活调用方 `services/aiAgent.ts` 第 368 行的 `/api/agent/run` 回退分支改为优雅降级（「复杂任务请到 Agent 面板处理」）。
- **T6 前端流式协议核查 → 伪债关闭**：全仓流式解析点仅 2 处且分属不同功能（Chat=NDJSON `chatApi.ts`、Agent=SSE `agent-workflow.tsx`），无重复实现；`aiAgent.ts` 仅做本地工具分发，从不实现第二套聊天流。关闭。
- **T9 导入陷阱彻底解决**：`agent_service` 从 `backend/scripts/` 移入 `backend/server/agent_service.py`，删除 `backend/scripts/` 目录；`backend/server/__init__.py` 去除全部 `sys.path` 注入；后端改正规包导入（`from scripts import database` / `from . import agent_service` 等）；QA 脚本同步。两套隔离 QA 全绿（space 26/26、agent-runner 19/0），DB 路径隔离仍有效。

待办（仅剩）：**T10 初始化 git + 固化 QA 脚本为回归**（需用户决策是否引入版本控制）。

---

## [v0.1] - 2026-07-28 · 独立 FastAPI 后端 + LLM 可配置化

### 架构
- **OpenClaw 全量移除**：代码 / 配置 / 文档中不再依赖 OpenClaw；LLM 改为任意 OpenAI 兼容端点（设置页或 `backend/.env` 配置）。
- **后端独立化**：从「Vite 插件式后端」迁移为独立 FastAPI 服务（`uvicorn backend.server.main:app`，端口 8000，多 worker）。
- **零 SDK LLM 客户端**：`backend/server/llm.py` 用标准库 `urllib` 实现 OpenAI 兼容客户端，不引入 `openai` SDK。
- **前端巨石拆分**：5 个 Hub（paper/chat/knowledge/software/task）按 barrel 模式零破坏性拆分。
- **前端设计语言**：确立苹果 HIG 风（Manrope + Space Grotesk 字体、`.glass` 毛玻璃、近黑字 + 单一蓝强调色、径向晕染纵深）。
- **数据库异步化 + WAL**：`aiosqlite` + `journal_mode=WAL; busy_timeout=5000`，每请求独立连接，支持多 worker 并发。

---

## 更早（参考，约 2026-03）

- 项目立项与早期设计文档（`DESIGN.md` / `FEATURES.md`），已在本次重构中归档至 `.archive/`。
- 初始 Hub 骨架（Dashboard / Paper / Software 等）搭建。

---

> 记法说明：本项目无正式 release 流程，版本号用于标记文档与架构的关键转折点。
