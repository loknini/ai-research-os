# 数据模型与空间隔离

> 实现文件：`scripts/database.py`（2137 行，aiosqlite）；引导壳：`backend/server/db.py`
> 核对日期：2026-07-30

---

## 1. 存储概览

| 项 | 值 |
|---|---|
| 数据库 | SQLite 单文件，默认 `<项目根>/data/ai_research_os.db` |
| 覆盖方式 | `DB_PATH`（优先） > `DATA_DIR`/ai_research_os.db > 默认 |
| 驱动 | `aiosqlite`（异步）；`scripts/obsidian_service.py` 是唯一例外，仍用同步 `sqlite3` |
| 表数量 | **20 张**（全部纳入空间隔离） |
| 索引 | 约 35 个业务索引 + 20 个 `idx_<table>_space` |
| 时间戳 | 毫秒级 Unix 时间戳 `int(time.time() * 1000)`；例外：`obsidian_vaults` 的 DDL 默认值是秒级 |
| 文件产物 | `data/papers/<space_id>/pdfs/`、`data/memory/<space_id>.md`、`data/.swanlab/config.json`（全局） |

### 连接管理

```python
@asynccontextmanager
async def get_db():   # 每次调用新建独立连接，绝不跨协程复用
    ...
```

建连后立即执行的 PRAGMA：

| PRAGMA | 值 | 作用 |
|---|---|---|
| `journal_mode` | `WAL` | 读写不互斥，多 worker 并发的前提（DB 级持久属性，重复设置无害） |
| `synchronous` | `NORMAL` | WAL 下的性能/安全折中 |
| `busy_timeout` | `5000` | 抗瞬时锁竞争，避免 `database is locked` |
| `foreign_keys` | `ON` | 启用外键与级联删除 |

正常退出 `commit()`，异常 `rollback()` 后重抛，`finally` 一律 `close()`。

### 命名约定

数据库列一律 `snake_case`；每张表配一个 `*_to_dict()` 转换器，输出 **`camelCase`** 给前端（`arxiv_id` → `arxivId`、`local_path` → `localPath`），并在此处对 JSON 列做 `json.loads`。所有读写函数签名都带 `space_id: str = DEFAULT_SPACE`。

---

## 2. 空间隔离（space-key 软隔离）

### 2.1 模型

```
用户填写口令 "lab-zhang"
        │  前端 SpaceGate 校验（>= 4 字符）
        ▼
apiMonitor 注入  X-Space-Key: lab-zhang
        │  后端 deps.normalize_space_key：trim + lower，不 hash
        ▼
space_id = "lab-zhang"  →  每条 SQL 带 WHERE space_id = ?
```

无账号、无密码、无 session。空间之间是**数据视图隔离**，不是安全边界——知道口令即可访问，适用于可信内网小团队。

### 2.2 隔离范围

**参与隔离的 20 张表**（`SPACE_TABLES`）：

```
papers            cron_jobs         software_projects   tasks
code_generations  notes             note_links          experiments
experiment_runs   version_history   conversations       chat_messages
agent_sessions    agent_messages    agent_generated_files
formula_history   obsidian_vaults   obsidian_files
agent_runs        agent_run_events
```

**不隔离（全局）**：LLM 配置、SwanLab 配置、CORS/服务参数、备份导出（整库）、Skills 目录。

### 2.3 迁移机制

`init_db()` 末尾对每张表执行幂等迁移：

```sql
PRAGMA table_info(<table>);                        -- 检查是否已有 space_id
ALTER TABLE <table> ADD COLUMN space_id TEXT NOT NULL DEFAULT '__default__';
CREATE INDEX IF NOT EXISTS idx_<table>_space ON <table>(space_id);
```

存量数据因此自动归入 `__default__` 空间。`agent_runs` / `agent_run_events` 是后加的表，`space_id` 直接写在建表 DDL 里且为显式参数（非默认值）。

子表（`note_links` / `chat_messages` / `experiment_runs` / `agent_messages` / `code_generations`）**反范式冗余写入父实体的空间**，保证任何查询都能单列过滤、无需 JOIN。

---

## 3. 表结构

> 所有表均额外含 `space_id TEXT NOT NULL DEFAULT '__default__'`，下表不再重复列出。

### 3.1 论文

**`papers`** — 主键 `id TEXT`

| 字段 | 说明 |
|---|---|
| `title` / `abstract` | 标题与摘要 |
| `authors` / `categories` / `tags` | JSON 数组 |
| `arxiv_id` | **UNIQUE NOT NULL**，去重依据 |
| `pdf_url` / `local_path` | 远程链接与本地归档路径 |
| `summary` | AI 总结结果（可为空） |
| `is_read` / `is_favorite` | 阅读态与收藏 |
| `published_date` / `added_at` / `updated_at` | 时间戳 |

### 3.2 任务与项目

**`software_projects`** — 主键 `id TEXT`
`name` / `description` / `idea_description` / `tech_stack`(JSON) / `status`(design·developing·testing·deployed·archived) / `local_path` / `github_url` / `architecture`(JSON) / `features`(JSON) / `milestones`(JSON) / `ai_generated_code` / 时间戳

**`tasks`** — 主键 `id TEXT`
`title` / `description` / `status`(todo·in_progress·done·archived) / `priority`(low·medium·high·urgent) / `deadline` / `tags`(JSON) / `project_id`→FK / `parent_task_id`（自引用，支持子任务树） / `ai_suggested` / `completed_at` / 时间戳

**`code_generations`** — 主键 `id TEXT`
`project_id`→FK CASCADE / `prompt` / `generated_code` / `file_path` / `language` / `status`(pending·applied·rejected)

### 3.3 知识

**`notes`** — 主键 `id TEXT`
`title` / `content` / `summary` / `type`(note·idea·summary·code_snippet) / `tags`(JSON) / `paper_id`→FK / `project_id`→FK / `parent_note_id` / `is_favorite` / `ai_generated` / 时间戳
> `update_note()` 内部会自动调用 `create_version()` 生成版本快照。

**`note_links`** — 复合主键 `(source_note_id, target_note_id)`，双 FK CASCADE，实现笔记双链。

### 3.4 实验

**`experiments`** — 主键 `id TEXT`
`name` / `description` / `project_id`→FK / `status`(planning·running·completed·failed) / `config`(JSON) / `tags`(JSON) / `swanlab_project` / `swanlab_experiment_id` / `total_runs` / `best_metric_name` / `best_metric_value REAL` / 时间戳

**`experiment_runs`** — 主键 `id TEXT`
`experiment_id`→FK CASCADE / `run_number` / `status`(running·completed·failed·aborted) / `config`(JSON) / `metrics`(JSON) / `swanlab_run_id` / `started_at` / `ended_at` / `duration`

### 3.5 对话

**`conversations`** — `id TEXT` / `title`（默认「新对话」） / 时间戳
**`chat_messages`** — `id TEXT` / `conversation_id`→FK CASCADE / `role`(user·assistant·system) / `content` / `timestamp` / `metadata`(JSON)

### 3.6 Agent

**`agent_sessions`** — `id TEXT` / `project_id`→FK CASCADE / `session_type` / `status`(running·completed·failed) / `input_data`(JSON) / `output_data`(JSON) / `progress`(0-100) / `current_step` / `error_message` / 时间戳
**`agent_messages`** — `id TEXT` / `session_id`→FK CASCADE / `agent_role` / `message_type`(thinking·action·output·error) / `content` / `step_name` / `metadata`(JSON)
**`agent_generated_files`** — `id TEXT` / `session_id`→FK CASCADE / `file_path` / `content` / `file_type` / `description`

**`agent_runs`**（后台运行主表）— `id TEXT` / `space_id NOT NULL`(DDL 内建) / `project_id` / `requirement` / `roles`(JSON) / `status`(pending·running·completed·failed·cancelled) / `error_message` / `result_summary`(JSON) / `created_at` / `started_at` / `completed_at`

**`agent_run_events`**（事件流）— `id INTEGER AUTOINCREMENT`（**SSE 游标**） / `run_id` / `space_id NOT NULL` / `type` / `data`(JSON，与 SSE 帧同构) / `created_at`

> `agent_run_events.id` 自增是 SSE 增量推送的核心：`get_agent_run_events(after_id=last_id)` 靠它做游标。

### 3.7 其他

**`version_history`** — `id TEXT` / `entity_type` / `entity_id` / `version_number` / `data`(JSON 全量快照) / `change_summary` / `created_by` / `created_at`
> 支持 note / task / project 三类实体；`delete_old_versions(keep_count=20)` 控制膨胀。

**`cron_jobs`** — `id TEXT` / `name` / `description` / `schedule` / `command` / `enabled` / `last_run` / `next_run` / `run_count`
**`formula_history`** — `id TEXT` / `image_data`(Base64) / `latex_code` / `confidence REAL` / `source_type`(upload·paste·screenshot) / `is_favorite` / `tags`(JSON) / `note`
**`obsidian_vaults`** — `id INTEGER` / `name` / `vault_path` / `sync_mode` / `last_sync_at` / `is_active`
**`obsidian_files`** — `id INTEGER` / `vault_id`→FK / `relative_path` / `file_hash` / `modified_time` / `content_preview` / `frontmatter` / `tags` / `links` / `backlinks` / `sync_status`

---

## 4. `database.py` 函数分组

| 分组 | 代表函数 |
|---|---|
| 基础设施 | `get_db` · `_fetchall` · `_fetchone` · `init_db` |
| 论文 | `get_all_papers` · `get_paper_by_arxiv` · `insert_paper` · `update_paper` · `delete_paper` · `get_papers_count` |
| 任务 | `get_all_tasks` · `insert_task` · `update_task` · `delete_task` · `get_tasks_by_project` |
| 项目 | `get_all_projects` · `get_project_by_id` · `insert_project` · `update_project` · `delete_project` |
| 代码生成 | `get_code_generations_by_project` · `insert_code_generation` · `update_code_generation_status` |
| 笔记 | `get_all_notes` · `get_note_links` · `get_linked_notes` · `insert_note` · `update_note`(触发版本) · `add_note_link` |
| 实验 | `get_all_experiments` · `get_experiment_runs` · `insert_experiment_run` · `update_experiment_run` |
| 版本 | `create_version` · `get_versions` · `compare_versions` · `restore_version` · `delete_old_versions` |
| 对话 | `get_all_conversations` · `insert_chat_message` · `get_conversation_messages` |
| 搜索 | `global_search(query, space_id, limit)` |
| Agent 会话 | `create_agent_session` · `update_agent_session` · `add_agent_message` |
| Agent 后台运行 | `create_agent_run` · `update_agent_run` · `get_agent_run_status` · `add_agent_run_event` · `get_agent_run_events` · `list_agent_runs` · `cancel_agent_run` |
| Cron | `get_cron_jobs` · `create_cron_job` · `toggle_cron_job` · `run_cron_job` |

---

## 5. 更新语义约定

所有 `update_*` / `delete_*` 函数统一返回 **`rowcount > 0`**。这保证跨空间操作不会误报成功——用 A 空间的 key 去改 B 空间的记录，`WHERE id=? AND space_id=?` 匹配 0 行，返回 `False`，路由层转为 404。

> 这是 2026-07-29 空间隔离验收时修复的问题（QA 项 A3）。新增数据表或 CRUD 函数时务必沿用该语义。

---

## 6. 验证

```bash
# 空间隔离验收（26 项：跨空间隔离、400 校验、20 路并发、WAL、连接不共享、表结构等）
python scripts/qa_verify_space.py

# 后台 Agent runner 验收（19 项）
python scripts/qa_verify_agent_runner.py
```

两个脚本都使用隔离的临时 `DATA_DIR` + 真实 aiosqlite + `TestClient`，不会污染现有数据库。运行需要 `aiosqlite / fastapi / httpx / uvicorn`。
