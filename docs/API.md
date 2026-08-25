# API 参考

> 全部 **93 条 `/api/*` 路由 + 1 条根路由**，按 router 分组。核对日期：2026-07-30
> 交互式文档：服务启动后访问 `http://localhost:8000/docs`（FastAPI 自动生成）

---

## 通用约定

### 空间头

除标注为「全局」的接口外，所有请求必须带：

```
X-Space-Key: <你的空间口令>
```

服务端 `trim + lower` 归一化后直接作为 `space_id`。缺失或长度 < 4 → `400 SPACE_REQUIRED`。
前端由 `services/apiMonitor.ts` 统一注入，业务代码无需手动设置。

### 响应格式

成功响应各接口自定义（多数为 `{success: true, data: ...}` 或直接返回数据）。
错误响应统一为：

```json
{ "success": false, "error": "NOT_FOUND", "message": "论文不存在" }
```

错误码来源：`APIError`（自定义 code）、`HTTPException` → `HTTP_ERROR`、未捕获异常 → `INTERNAL_ERROR`。

### 命名风格

请求体与响应体字段一律 **camelCase**（数据库内部是 snake_case，由 `*_to_dict()` 转换）。

---

## 1. 健康检查 `health.py` · 全局

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/healthz` | 存活探针。返回 version、DB 路径与是否存在。零外部依赖，任何时候都应 200 |
| GET | `/api/llm/status` | LLM 配置与可达性。30s TTL 缓存，探测走 `asyncio.to_thread` 不阻塞事件循环 |
| GET | `/` | 服务元信息 `{success, name, version, docs, health}` |

---

## 2. 全局搜索 `search.py`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/search?q=&limit=50` | 跨 papers / tasks / projects / notes / experiments 搜索 |

---

## 3. Agent `agent.py` — prefix `/api/agent`

### 3.1 后台运行（推荐）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/agent/runs` | 提交后台运行，**立即返回** `{runId, status:"running"}`，不阻塞 |
| GET | `/api/agent/runs?projectId=&limit=50` | 运行列表（limit 1..200） |
| GET | `/api/agent/runs/{run_id}?after=0` | 轮询单个运行，返回 `{run, events[], pendingApprovals[], done}`；`after` 为事件游标 |
| GET | `/api/agent/runs/{run_id}/stream` | **SSE** 实时事件流（DB 轮询 0.6s，跨 worker 安全） |
| POST | `/api/agent/runs/{run_id}/cancel` | 取消运行（内存 Event + DB 状态双写） |
| POST | `/api/agent/runs/{run_id}/approvals/{approval_id}` | **工具审批决策**：`{approved: bool}`；仅 pending 生效，决策后 runner 轮询恢复 |
| GET | `/api/agent/runs/{run_id}/approvals` | 列出该运行全部工具审批记录（含历史，审计用） |
| GET | `/api/agent/runs/{run_id}/replay` | **可重放会话日志**：按 `(phase, round)` 返回模型实际看到的消息序列 |

**请求体**（`POST /runs`）：

```json
{ "requirement": "做一个论文阅读进度追踪工具", "projectId": "可选", "roles": ["architect","planner"] }
```

`roles` 省略时使用 `backend/agent_roles.json` 的启用顺序。

**审批决策**（`POST /runs/{run_id}/approvals/{approval_id}`）：

```json
{ "approved": true }
```

- 审批模式由 `AGENT_APPROVAL_MODE` 控制：`auto`（默认，sensitive 直通）/ `manual`（sensitive 等待审批）/ `strict`（sensitive + dangerous 均等待审批）。
- `dangerous` 工具在非 strict 模式一律拒绝（fail-closed）；未提供审批通道的调用方同样拒绝。
- 超时（`AGENT_APPROVAL_TIMEOUT`，默认 300s）按拒绝处理；取消运行会把待审批项标记为 `cancelled`。

### 3.2 会话与兼容接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/agent/run` | SSE 直跑角色管线（**会阻塞该 worker 协程**，保留兼容） |
| POST | `/api/agent/collaborate` | 同上，历史别名，共用同一 handler |
| POST | `/api/agent/sessions` | 创建 agent session |
| GET | `/api/agent/sessions?projectId=` | session 列表 |
| GET | `/api/agent/sessions/{session_id}/messages` | session 消息 |

### 3.3 SSE 事件帧

```
data: {"type":"run_start", ...}
data: {"type":"phase_start","role":"architect","label":"架构师"}
data: {"type":"start", ...}
data: {"type":"complete","role":"architect","output":"...","parsed":{...}}
data: {"type":"run_complete"} | {"type":"run_cancelled"} | {"type":"error","message":"..."}
data: [DONE]
```

新增内部能力事件（2026-08-21）：

- `tool_approval`：工具审批状态。`{type, approvalId, tool, parameters, policy, status}`，`status` 为 `pending` / `approved` / `denied` / `timed_out` / `cancelled`。前端据 `pending` 弹审批卡片，据终态移出队列。
- `context_compressed`：上下文超预算被压缩。`{type, agent, round, message}`。

响应头带 `Cache-Control: no-cache` 与 `X-Accel-Buffering: no`（禁 nginx 缓冲）。

---

## 4. 对话 `chat.py` — prefix `/api/chat`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat/completions` | ReAct 流式对话 |
| POST | `/api/chat/completions/stream` | 同上，别名，共用 handler |

**空间语义特例**：缺 `X-Space-Key` 时不报 400，静默回落 `__default__`。

**协议：NDJSON（逐行 JSON，非标准 SSE，无 `data:` 前缀）**

| 帧 type | 载荷 |
|---|---|
| `text` | 增量文本内容 |
| `tool_start` | 工具调用开始（名称 + 参数） |
| `tool_result` | 工具执行结果 |
| `context` | `{estimated_tokens, limit, compressed}`，前端据此显示上下文占用 |
| `error` | 错误信息 |

流末尾输出裸标记 `[DONE]`，异常时为 `[ERROR]<msg>`。

**特性**：多轮工具循环（ReAct）、超限时自动 LLM 压缩历史（阈值 `CONTEXT_TOKEN_LIMIT`，默认 16000）、注入该空间的持久记忆、`/skill` 命令短路直接调用技能。

---

## 5. 论文 `papers.py` — prefix `/api/papers`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/papers?limit=100&offset=0` | 论文列表 |
| POST | `/api/papers/fetch` | 从 arXiv 抓取并入库，返回 `{papers, inserted, count}` |
| DELETE | `/api/papers/{paper_id}` | 删除 |
| POST | `/api/papers/{paper_id}/download` | 下载 PDF 到 `data/papers/<space_id>/pdfs/` 并回写 `localPath` |
| POST | `/api/papers/{paper_id}/summarize` | AI 总结；LLM 不可用时降级为规则摘要，响应含 `source: "llm" \| "fallback"` |

---

## 6. 任务 `tasks.py` — prefix `/api/tasks`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tasks?projectId=&status=` | 任务列表 |
| POST | `/api/tasks` | 创建（服务端生成 uuid + 毫秒时间戳） |
| PUT | `/api/tasks/{task_id}` | 更新（`exclude_none`，只改传入字段） |
| DELETE | `/api/tasks/{task_id}` | 删除 |

---

## 7. 项目 `projects.py` — prefix `/api/projects`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/projects?status=` | 项目列表 |
| POST | `/api/projects` | 创建 |
| GET | `/api/projects/{project_id}` | 详情 |
| PUT | `/api/projects/{project_id}` | 更新 |
| DELETE | `/api/projects/{project_id}` | 删除 |
| GET | `/api/projects/{project_id}/tasks` | 该项目下的任务 |

---

## 8. 笔记 `notes.py` — prefix `/api/notes`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/notes?noteType=&paperId=&projectId=` | 笔记列表 |
| POST | `/api/notes` | 创建 |
| GET | `/api/notes/{note_id}` | 详情 |
| PUT | `/api/notes/{note_id}` | 更新（**自动生成版本快照**） |
| DELETE | `/api/notes/{note_id}` | 删除 |

---

## 9. 实验 `experiments.py` — prefix `/api/experiments`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/experiments?status=&projectId=` | 实验列表 |
| POST | `/api/experiments` | 创建 |
| GET | `/api/experiments/{experiment_id}` | 详情 |
| PUT | `/api/experiments/{experiment_id}` | 更新（含 bestMetricName / bestMetricValue） |
| DELETE | `/api/experiments/{experiment_id}` | 删除 |
| GET | `/api/experiments/{experiment_id}/runs` | 运行记录列表 |

---

## 10. 会话 `conversations.py` — prefix `/api/conversations`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/conversations` | 列表 |
| POST | `/api/conversations` | 创建（可带初始 messages） |
| GET | `/api/conversations/{id}` | 详情 |
| PUT | `/api/conversations/{id}` | 更新 title / updatedAt |
| DELETE | `/api/conversations/{id}` | 删除（级联删消息） |
| GET | `/api/conversations/{id}/messages` | 消息列表 |
| POST | `/api/conversations/{id}/messages` | 追加消息 |

---

## 11. 版本历史 `versions.py` — prefix `/api/versions`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/versions/{entity_type}/{entity_id}?limit=50` | 某实体的版本列表 |
| GET | `/api/versions/detail/{version_id}` | 单版本详情 |
| POST | `/api/versions/compare` | 比较，body `{versionId1, versionId2}` |
| POST | `/api/versions/restore` | 回滚，body `{versionId}` |

> ⚠️ 路由顺序陷阱：`/detail/{id}` 定义在 `/{entity_type}/{entity_id}` 之后，因此 `entity_type == "detail"` 会被前者抢先匹配。目前无实体类型叫 detail，暂不影响。

---

## 12. 定时任务 `cron.py` — prefix `/api/cron`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/cron/jobs` | 任务列表 |
| POST | `/api/cron/jobs` | 创建 |
| POST | `/api/cron/jobs/{job_id}/toggle` | 启停切换 |
| POST | `/api/cron/jobs/{job_id}/run` | 立即执行（`shlex.split` + subprocess，30s 超时，注入 `SPACE_ID`/`DATA_DIR`，输出截断 2000 字符） |
| DELETE | `/api/cron/jobs/{job_id}` | 删除 |

---

## 13. 设置 `settings.py` — prefix `/api/settings` · 全局

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/settings/llm` | 读取 LLM 配置（apiKey 掩码） |
| POST | `/api/settings/llm` | 保存：① 热改配置单例 ② 同步 `os.environ` ③ upsert 项目根 `.env` |
| GET | `/api/settings/llm/models?baseUrl=&apiKey=` | 拉取模型列表，兼容 OpenAI `data[].id` 与 Ollama `models[].name`，去重保序 |
| POST | `/api/settings/llm/test` | 发一条 `max_tokens=1` 的 ping，报告延迟；对 401/403/404/429 给出中文诊断 |

> 保存后**当前进程立即生效**，无需重启；但多 worker 模式下只有处理该请求的 worker 会热更新，其余 worker 靠 `.env` 在下次重启后对齐。**多 worker 下改配置建议重启服务。**

---

## 14. 技能 `skills.py` — prefix `/api/skills` · 全局

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/skills` | 列出全部技能（含已禁用），带 `type`/`enabled`/`hasScript`/`path` |
| POST | `/api/skills/reload` | 重扫技能目录，返回生效数量 |
| POST | `/api/skills/{name}/enabled` | 启停（改写 SKILL.md frontmatter 的 `enabled` 行） |
| POST | `/api/skills/{name}/run` | 直接调用技能 |

---

## 15. SwanLab `swanlab.py` — prefix `/api/swanlab` · 全局

全部经 `run_script("swanlab_api.py", ...)` subprocess 执行。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / POST | `/api/swanlab/config` | 读取 / 保存配置（apiKey、apiUrl、enabled、defaultWorkspace） |
| POST | `/api/swanlab/test` | 测试连接 |
| POST | `/api/swanlab/fetch` | 拉取实验数据 |
| GET | `/api/swanlab/workspaces` | 工作空间列表 |
| GET | `/api/swanlab/projects` | 项目列表 |
| GET | `/api/swanlab/experiments?project=` | 实验列表 |
| GET | `/api/swanlab/experiment/detail?project=&expId=` | 实验详情 |
| GET | `/api/swanlab/cache` | 本地缓存数据 |
| GET | `/api/swanlab/status` | 集成状态 |

---

## 16. 备份 `backup.py` — prefix `/api/backup` · 全局

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/backup/export` | 整个 `DATA_DIR` 打包为 zip 流式返回，含 `manifest.json`；DB 先复制到临时文件再入包；排除 `.git`/`.swanlab`/`.cache`/`__pycache__` |
| POST | `/api/backup/import` | 上传 zip（字段名 `file`，≤500MB，仅 `.zip`）：校验 manifest `app == ai-research-os` → Zip Slip 防护 → `testzip()` → 先 `copytree` 到 `.backup-<时间戳>` → 再覆盖 |

> 导入是**整库覆盖**，会替换所有空间的数据。DB 被占用时通过响应里的 `note` 字段报告，不抛错。

---

## 17. 公式识别 `formula.py` — prefix `/api/formula`

经 `run_script("formula_service.py", ...)`，通过 `SPACE_ID` 环境变量传空间。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/formula/recognize` | 识别，body 支持 `imagePath` 或 `imageBase64`（后者落临时文件，finally 清理） |
| GET | `/api/formula/history?favorites=&limit=100` | 识别历史 |
| PUT | `/api/formula/history` | 更新记录（isFavorite / tags / note） |
| DELETE | `/api/formula/history/{record_id}` | 删除记录 |
| GET | `/api/formula/stats` | 统计 |

---

## 18. 引用生成 `citation.py` — prefix `/api/citation` · 全局

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/citation/search?q=` | Crossref 检索（q 为空 → 400） |
| POST | `/api/citation/generate` | 根据 paper 对象生成引用（APA / MLA / Chicago / GB7714 / BibTeX / RIS） |

---

## 19. Obsidian `obsidian.py` — prefix `/api/obsidian`

经 `run_script("obsidian_service.py", ...)`，注入 `SPACE_ID`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/obsidian/vaults` | vault 列表 |
| POST | `/api/obsidian/vaults` | 添加 vault（name / path） |
| POST | `/api/obsidian/vaults/{vault_id}/scan` | 扫描（vault_id 为整数） |
| GET | `/api/obsidian/vaults/{vault_id}/files` | 文件列表 |
| GET | `/api/obsidian/files/{file_id}` | 读取文件内容 |

---

## 20. 持久记忆 `memory.py` — prefix `/api/memory`

存储位置：`data/memory/<space_id>.md`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/memory` | 读取该空间记忆全文 |
| PUT | `/api/memory` | 整体覆盖，body `{content}` |
| POST | `/api/memory/observe` | 追加一条，body `{entry}` |
| POST | `/api/memory/extract` | 从 `messages` 中由 LLM 提炼事实并追加 |

---

## 附录：curl 速查

```bash
KEY="my-space"

# 健康检查（无需空间头）
curl http://localhost:8000/api/healthz
curl http://localhost:8000/api/llm/status

# 论文
curl -H "X-Space-Key: $KEY" "http://localhost:8000/api/papers?limit=10"
curl -X POST -H "X-Space-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"query":"diffusion model","maxResults":10}' \
  http://localhost:8000/api/papers/fetch

# 任务
curl -X POST -H "X-Space-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"title":"读完 DDPM","priority":"high"}' \
  http://localhost:8000/api/tasks

# Agent 后台运行 + 跟流
RID=$(curl -s -X POST -H "X-Space-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"requirement":"设计一个实验记录工具"}' \
  http://localhost:8000/api/agent/runs | python -c "import sys,json;print(json.load(sys.stdin)['runId'])")
curl -N -H "X-Space-Key: $KEY" "http://localhost:8000/api/agent/runs/$RID/stream"

# 备份导出
curl -X POST http://localhost:8000/api/backup/export -o backup.zip
```
