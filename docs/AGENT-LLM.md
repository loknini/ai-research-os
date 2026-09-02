# LLM、Agent 与 Skills

## 0. 0.5.0 实际研发 Runner 与可配置专家团队

`development_runner.py` 负责固定的分析、实现、测试、审查循环。模型输出结构化完整文件，`development_workspace.py` 在服务器绑定的隔离根目录下校验相对路径并原子写入；验证命令使用 `shell=False`，只接受 pytest/unittest 与 package.json scripts。运行、阶段、租约、检查点和证据都落 SQLite，服务重启后可安全重新领取。

Git 项目在独立 worktree/分支中运行，普通目录复制到受控副本。Runner 通过测试且审查接受后只进入 `awaiting_apply`，不会自动修改原项目；应用端点再次校验 base revision 和差异摘要，冲突时不做部分写入。这是工作区隔离与命令白名单，不是容器级沙箱。

右下角 AI 助手复用 Chat Hub 的 `chatGenerationManager`、会话数据库和 `/api/chat/completions/stream`，不再使用前端关键词匹配器。

## 0.1 0.4.0 可配置专家团队

`backend/server/agent_teams.py` 负责加载版本控制内的内置团队、校验用户团队、解析当前空间的论文/笔记上下文，并按边数组顺序拼装汇合输入。`agent_runner.py` 在旧顺序 `roles` 入口之外增加静态 DAG 拓扑调度：ready 节点在团队 `maxConcurrency`（1–4）内并行执行，节点状态和输出写入 `agent_run_nodes`。

团队节点可覆盖模型、temperature、maxTokens，且只能看到 `allowedTools` 白名单。工具安全等级仍由注册表决定，团队不能降级策略。JSON Schema 输出由 `jsonschema` 校验，首次失败后执行一次无工具修复；仍失败则节点失败，后代跳过，主要输出未完成时整次运行失败。

内置定义位于 `backend/agent_teams/*.json`，用户团队和角色模板按 space-key 入库。每次运行保存团队与输入上下文快照；旧 `backend/agent_roles.json` 和 `roles` 请求继续可用。

> 版本以 `docs/_meta.json` 为准；核对日期：2026-09-02

---

## 1. LLM 客户端

### 1.1 设计

`backend/server/llm.py`（246 行）用 **Python 标准库 `urllib.request`** 手写 OpenAI 兼容客户端，不引入 `openai` SDK。`requirements.txt` 里对此有明确注释。

| 方法 | 语义 | 失败行为 |
|---|---|---|
| `call_llm(messages, *, model, temperature, max_tokens, timeout)` | 非流式，返回 `str \| None` | **吞掉所有异常返回 `None`**，由调用方降级 |
| `stream_llm(messages, *, ..., tools)` | 生成器：先逐个 yield 文本 delta（`str`）；流结束后若有工具调用，再 yield 一个 `dict` `{"tool_calls":[{id,name,arguments}]}` | 连接失败抛 `LLMUnavailableError` |
| `is_available()` / `status()` | 配置检查 + TCP 层可达性探测（`socket.create_connection`，3s 超时） | 返回布尔/状态字典 |

模块底部导出单例 `llm_client = LLMClient()`，构造时绑定 `config.settings` 引用——所以设置页热改配置能立刻对后续请求生效。

### 1.2 URL 拼接规则（易错点）

```
endpoint = LLM_BASE_URL.rstrip("/") + LLM_HTTP_PATH
```

采用 **OpenAI SDK 风格：Base URL 自带 `/v1`**。

| 提供方 | `LLM_BASE_URL` | `LLM_HTTP_PATH` | 实际请求 |
|---|---|---|---|
| 硅基流动 | `https://api.siliconflow.cn/v1` | `/chat/completions` | `.../v1/chat/completions` |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `/chat/completions` | `.../v4/chat/completions` |
| Ollama | `http://localhost:11434/v1` | `/chat/completions` | `.../v1/chat/completions` |

`config.py` 有一处兼容补丁：base 以 `/v1` 结尾且 path 以 `/v1/` 开头时自动剥掉重复前缀（仅影响运行时内存配置，不改 `.env`）。

### 1.3 流式与 function calling

- **SSE 解析手写**：跳过空行与 `:` 注释行，只处理 `data:` 前缀，遇 `[DONE]` 跳出。
- **工具调用分片累积**：用 `tool_acc: Dict[int, {...}]` 按 `index` 累积——`id` 覆盖写，`name` / `arguments` 字符串拼接；流结束后对 `arguments` 做 `json.loads`（失败保留原始串）。
- 传了 `tools` 时 payload 自动附加 `tool_choice: "auto"`。

### 1.4 各调用方与降级策略

| 调用点 | 方式 | LLM 不可用时 |
|---|---|---|
| `routers/chat.py` | `stream_llm(tools=TOOLS)` | 返回 error 帧 |
| `routers/papers.py` | `call_llm` | 降级 `generate_fallback_summary()`，响应标 `source:"fallback"` |
| `server/memory.py` | `call_llm(temperature=0.2, max_tokens=600)` | 不提炼，原样保留 |
| `chat.py::_summarize` | `call_llm(temperature=0.2, max_tokens=800)` | 不压缩，直接截断 |
| `agent_service.py` | `llm_client.call_llm()`，导入失败回退本地 `_legacy_call_llm` | 产出 `error` 事件 |
| `routers/settings.py` | **绕过 LLMClient**，自己用 urllib 打 `/models` 与 ping | — |

**核心原则**：所有 CRUD / 检索 / 版本 / 备份功能都不依赖 LLM。只有「论文总结、Chat、Agent、记忆提炼」四类需要。

---

## 2. Chat 的 ReAct 循环

`scripts/chat_agent_stream.py` 导出被 `routers/chat.py` 直接复用的四件套：`SYSTEM_PROMPT` / `TOOLS` / `execute_tool()` / `is_skill_tool()`。

### 2.1 内置工具（5 个静态）

| 工具 | 作用 |
|---|---|
| `fetch_papers` | 按关键词抓取 arXiv 论文并入库 |
| `create_task` | 创建任务 |
| `create_project` | 创建软件项目 |
| `create_note` | 创建笔记 |
| `get_stats` | 汇总各模块统计数据 |

`TOOLS` 数组在运行时会把 SkillBridge 扫到的 **tool 型技能动态并入**，因此模型看到的工具集 = 5 个静态 + N 个已启用技能。

### 2.2 单轮流程

```
用户消息
 → 载入会话历史
 → 注入该空间持久记忆（data/memory/<space_id>.md）
 → 估算 token，超过 Chat 的 CONTEXT_TOKEN_LIMIT=16000（Agent 另用 AGENT_CONTEXT_TOKEN_LIMIT=24000）时调 LLM 压缩早期历史
 → stream_llm(messages, tools=TOOLS)
    ├─ 文本 delta      → SSE data: {"type":"text"}
    └─ tool_calls      → {"type":"tool_start"} → execute_tool() → {"type":"tool_result"}
                          → 结果回填 messages，再次进入 stream_llm（多轮循环）
 → {"type":"context", estimated_tokens, limit, compressed}
 → [DONE]
```

`/skill <name> <args>` 开头的消息会短路整个 LLM 循环，直接调用技能。

---

## 3. 旧角色兼容管线

### 3.1 抽象

未传 `teamId` 的旧请求继续使用本节的顺序管线：一个**角色（role）** = 一段 system prompt + 一个可选的结构化解析器，**上游的 `raw_output` 作为下游的 user 输入**。新功能应优先使用第 0 节的团队 DAG。

内置角色 `BUILTIN_ROLES`：

| key | label | parser | 产出 |
|---|---|---|---|
| `architect` | 架构师 | `design` | 正则抽取 6 段：概述 / 技术栈 / 目录结构 / 模块 / API / 数据模型 |
| `planner` | 规划师 | `plan` | 从 ```json 代码块或裸 `{"phases":...}` 抽 JSON |
| `developer` | 开发者 | 无 | 纯文本 |
| `reviewer` | 评审者 | 无 | 纯文本 |

### 3.2 配置 `backend/agent_roles.json`

```json
{ "roles": [
  { "key": "architect", "label": "架构师", "enabled": true  },
  { "key": "planner",   "label": "规划师", "enabled": true  },
  { "key": "developer", "label": "开发者", "enabled": false },
  { "key": "reviewer",  "label": "评审者", "enabled": true  }
] }
```

- **数组顺序 = 管线执行顺序**；当前生效管线为 架构师 → 规划师 → 评审者。
- 每个条目还可选携带 `system`（覆盖 system prompt）与 `parser`（`design` / `plan` / `null`），代码已支持，当前文件未使用。
- 文件缺失 / 解析失败 / 结果为空 → 回落默认管线 `["architect","planner","reviewer"]`。
- 单次请求可用 `POST /api/agent/runs` 的 `roles` 字段临时覆盖。

### 3.3 关键函数

| 函数 | 说明 |
|---|---|
| `load_role_config()` | 读配置，返回启用且存在于 BUILTIN_ROLES 的 key 列表，保持文件顺序 |
| `resolve_role(key)` | 合并内置默认与配置覆盖 |
| `run_role(key, input_text)` | 生成器：`start` → (`progress`) → `complete`；LLM 不可用则产出 `error` |
| `run_full_workflow(requirement, role_keys=None)` | 生成器：逐角色 `phase_start` + 转发 `run_role` 事件 + 末尾 `workflow_complete` |

### 3.4 模块导入约定（已规范化）

`agent_service` 现为 `backend/server/agent_service.py`（与 `agent_runner`、`db` 同包）。各模块统一使用**正规包导入**，历史上的「导入陷阱」（`sys.path` 注入 hack）已在 2026-07-31 根除：

- `backend/server/` 内模块互相引用：`from . import x`（包内相对），例如 `agent_runner.py` 用 `from . import agent_service, db`。
- `backend/server/` 引用顶层 `scripts/` 包内模块：`from scripts import database` / `from scripts import fetch_arxiv` / `from scripts.chat_agent_stream import execute_tool` / `from scripts.summarize_paper import ...`。
- `agent_service.py` 引用 LLM 客户端：`from backend.server.llm import llm_client, LLMUnavailableError`（带 try/except 回退到本地 `_legacy_call_llm`）。

顶层 `scripts/` 已是正规包（`scripts/__init__.py`），与后端共享同一模块对象，因此 QA 脚本通过 `from scripts import database` 覆盖 `DB_PATH` 的隔离手段仍然有效，真实库不会被测试污染。

---

## 4. 后台 Agent Runner

### 4.1 存在理由

`run_full_workflow` 是**同步阻塞生成器**（内部 LLM 走同步 urllib）。直接在 FastAPI 协程里迭代会卡死整个 worker 的事件循环，其他请求全部挂起。

### 4.2 执行模型

```
submit_run(space_id, requirement, project_id, roles)
  ├─ 生成 uuid，create_agent_run() 落库（status=pending）
  ├─ RUN_CANCEL[run_id] = threading.Event()
  ├─ _spawn() 起守护线程
  └─ 立即 return run_id                    ← HTTP 请求在此结束，不阻塞

守护线程 _worker()
  └─ asyncio.new_event_loop()              ← 线程内自建独立事件循环
     └─ _execute()
        ├─ 写 started_at，发 run_start
        ├─ for role in roles:
        │    ├─ 检查取消（内存 Event + DB status 双查）
        │    ├─ 发 phase_start
        │    └─ 转发 run_role 每一帧 → add_agent_run_event() 立即落库
        └─ 三态收尾：completed / failed / cancelled
```

### 4.3 双层取消

| 层 | 机制 | 覆盖范围 |
|---|---|---|
| 内存 | `RUN_CANCEL[run_id]` 的 `threading.Event` | 同 worker 内即时打断 |
| 数据库 | `cancel_agent_run()` 写 `status='cancelled'`，后台线程每阶段前复查 | **跨 worker 有效** |

### 4.4 SSE 推送

`GET /api/agent/runs/{id}/stream` **不是内存推送，而是 DB 轮询式 SSE**：维护 `last_id` 游标 → `get_agent_run_events(after_id=last_id)` 取增量 → 逐条 `data: {...}` 输出 → run 进终态后输出 `[DONE]`，否则 `await asyncio.sleep(0.6)`。

因为状态与事件都在共享 SQLite（WAL），**天然跨多 worker 可见**，这是能开 `--workers N` 的关键。

### 4.5 通道（旧同步已删除）

| 通道 | 端点 | 特点 |
|---|---|---|
| 后台 run（唯一） | `POST /api/agent/runs` + 轮询 / SSE / cancel | 非阻塞、可取消、可离开页面、有历史记录 |

旧 `POST /api/agent/run` / `/collaborate` 已于 2026-07-31 删除（见 `TECH-DEBT.md:T3`），前端已切后台 run；`hubs/agent-runs/` 提供运行历史与事件时间线。Chat 的切 Hub 不中断是前端 `chatGenerationManager` 单例实现，与此后台 runner 无关。

---

## 5. Agent Skills

### 5.1 目录约定

```
backend/skills/
└── <skill-name>/
    ├── SKILL.md          # frontmatter + 正文 = 技能本体
    └── scripts/          # 可选，tool 型技能的可执行文件
```

与 Claude Code / Codex 的 Agent Skills 开放标准目录约定兼容，技能可直接互换。

### 5.2 SKILL.md 格式

```yaml
---
name: arxiv_reader
description: 从 arXiv 抓取论文，返回结构化元数据。
type: tool                      # tool | instruction
command: ["python", "scripts/fetch_arxiv.py"]
timeout: 60
enabled: true
parameters: {"type":"object","properties":{...},"required":[]}
---

正文：使用约定、返回字段说明、边界。
```

`skills_bridge.py` 用**零依赖的极简 frontmatter 解析**（支持标量 + 单行/多行 JSON 块），不引入 PyYAML。

### 5.3 两种类型

| type | 有无可执行入口 | 使用方式 |
|---|---|---|
| `instruction` | 无 | 正文作为工作流提示词注入，引导模型按流程行动 |
| `tool` | 有 `command` | 注册为 function calling 工具；调用时 subprocess 执行，stdin 传 JSON 参数、stdout 读 JSON 结果，环境变量带 `X_SPACE_KEY` |

### 5.4 内置示例

| 技能 | type | 说明 |
|---|---|---|
| `arxiv-reader` | tool | 纯标准库从 arXiv Atom API 抓论文，返回结构化 JSON |
| `code-review` | instruction | 结构化代码评审工作流：`get_stats` 定范围 → 逐项检查正确性/可读性/健壮性/安全 → 用 `create_task`/`create_note` 沉淀 |
| `demo-echo` | tool | 冒烟测试：验证 stdin JSON / `X_SPACE_KEY` / stdout JSON 三段管线 |

### 5.5 安全边界

**命令只能来自受信任的 SKILL.md，模型只提供参数，永远无法指定执行什么命令。** 新增技能等同于新增可执行代码，需按代码审查对待。

---

## 6. 持久记忆

`backend/server/memory.py`，存储于 `data/memory/<space_id>.md`（纯 Markdown，可手工编辑）。

| 能力 | 说明 |
|---|---|
| 读 / 覆盖 / 追加 | `GET` / `PUT` / `POST /observe` |
| LLM 提炼 | `POST /extract`：从传入 messages 中提炼稳定事实并追加 |
| 注入 | Chat 请求时自动拼进 system prompt |

按空间隔离，每个 space 一份独立记忆文件。前端入口在「设置 → 记忆管理」。
