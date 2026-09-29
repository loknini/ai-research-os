# 部署与运维

> 版本以 `docs/_meta.json` 为准；核对日期：2026-09-02。

---

## 1. 环境要求

| 工具 | 版本 | 必需 |
|---|---|---|
| Python | ≥ 3.10（实测 3.12 / 3.13） | 是 |
| Node.js | ≥ 22 | 是（仅前端） |
| Git | 任意 | 使用 Git 项目或新建受管理研发项目时需要；普通目录副本模式可不用 |

后端直接依赖共 11 个包（`backend/requirements.txt`）：

```
fastapi>=0.110      uvicorn[standard]>=0.29   pydantic>=2.6
pydantic-settings>=2.2   python-dotenv>=1.0   requests>=2.31
python-multipart>=0.0.9  aiosqlite>=0.20       jsonschema>=4.22,<5
PyMuPDF>=1.24           sqlite-vec==0.1.9
```

`requests` 只给 `scripts/formula_service.py` 用；`python-multipart` 给备份上传用；`jsonschema` 校验专家团队节点的结构化输出；`PyMuPDF` 解析 RAG PDF；`sqlite-vec` 加速本地向量候选检索。**没有 openai SDK**，LLM 客户端是标准库实现。sqlite-vec 扩展缺失时 RAG 仍可回退 FTS5 + 流式余弦，但正式安装将其作为默认依赖并在启动时做扩展加载冒烟检查。

### 研发工作区安全边界

研发运行写入 `data/dev_workspaces/<space>/<run>/`。Git 项目必须先保持工作区干净，普通目录应用前会核对源文件哈希；Agent 不会自动 push，也不会在完成时自动应用。执行层使用参数数组与命令白名单，不支持任意 shell、联网或自动安装依赖。它不是容器级沙箱，因此只应绑定操作者明确授权的项目目录；高风险或不可信代码仍应在独立虚拟机/容器中运行。

---

## 2. 启动

### 2.1 一键脚本（推荐）

```powershell
# Windows
.\start.ps1                      # 后端 :8000 + 前端 :5173；默认后台运行且不弹新终端
.\start.ps1 -SkipFrontend        # 仅后端
.\start.ps1 -SkipBackend         # 仅前端
.\start.ps1 -SkipLLM             # 跳过 LLM 可用性校验
.\start.ps1 -ApiPort 9000        # 自定义后端端口
.\start.ps1 -ApiWorkers 4        # 交互模式可指定；Windows 后台模式固定单 worker
.\start.ps1 -DataDir D:\Sync\airos-data   # 覆盖数据目录
.\start.ps1 -ShowTerminals         # 调试时为前后端分别打开可见终端
```

```bash
# Linux / macOS
./start.sh
./start.sh --data-dir ~/Sync/airos-data
```

脚本首次运行会在项目根创建 `.venv`；每次启动会按 `backend/requirements.txt` 内容指纹和直接依赖导入结果检查环境，requirements 变化或包缺失时自动补装。依赖始终安装在 `.venv`，**不污染系统全局 Python**（仅创建 venv 那一刻用全局解释器）。

### 2.2 手动启动

```bash
# 终端 1 — 后端
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.server.main:app --port 8000 --workers 4

# 终端 2 — 前端
cd frontend && npm install && npm run dev
```

开发态访问 `http://localhost:5173`（`/api` 经 Vite 代理转 `:8000`）。

### 2.3 生产部署（单进程托管）

```bash
cd frontend && npm run build      # 产出 frontend/dist
cd .. && python -m uvicorn backend.server.main:app --host 0.0.0.0 --port 8000 --workers 4
```

`frontend/dist` 存在时 uvicorn 会自动挂载为 SPA（`StaticFiles(html=True)`），`/api/*` 路由优先。**无需 nginx**。

> ⚠️ **不要加 `--reload`**：与 `--workers` 互斥，且会导致 Agent 后台线程被反复杀死。

---

## 3. 配置

### 3.1 `.env` 加载顺序

先 `<项目根>/.env`，再 `<项目根>/backend/.env`，均为 `override=False`（先到先得）。样例见 `backend/.env.example`。

### 3.2 环境变量清单

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_BASE_URL` | `""` | **必须含 `/v1`**（OpenAI SDK 风格） |
| `LLM_API_KEY` | `""` | |
| `LLM_MODEL` | `""` | |
| `LLM_TEMPERATURE` | `0.7` | |
| `LLM_MAX_TOKENS` | `4000` | |
| `LLM_TIMEOUT` | `120` | 秒 |
| `LLM_HTTP_PATH` | `/chat/completions` | 与 base 拼接成最终 endpoint |
| `CONTEXT_TOKEN_LIMIT` | `16000` | Chat 上下文压缩阈值（`backend/server/context.py:24`） |
| `AGENT_CONTEXT_TOKEN_LIMIT` | `24000` | Agent 角色内上下文阈值（实现位于 `backend/server/agents/service.py`） |
| `AGENT_CONTEXT_KEEP_LAST` | `6` | Agent 保留末尾消息数 |
| `DB_PATH` | 无 | 直接指定 DB 文件，优先级高于 `DATA_DIR` |
| `DATA_DIR` | `<项目根>/data` | 数据目录，脚本与文件归档均以此为根 |
| `APP_HOST` | `0.0.0.0` | |
| `APP_PORT` | `8000` | |
| `ADMIN_TOKEN` | `""` | 远程系统管理令牌；本机免令牌，远程设置/备份/SwanLab/Skills 必须提供 |
| `CORS_ORIGINS` | `*` | 逗号分隔；为 `*` 时自动关闭 credentials |
| `LOG_DIR` | `<项目根>/logs` | 长期日志目录；相对路径以项目根解析 |
| `LOG_LEVEL` | `INFO` | 应用日志最低级别 |
| `LOG_RETENTION_DAYS` | `30` | 运行日志及归档的保留天数 |
| `LOG_MAX_FILES` | `500` | 日志文件总数上限；活跃 Worker 文件不会被删除 |

### 3.3 LLM 配置（三选一）

**方式 A — 界面配置（推荐）**：「设置 → LLM API 配置」填 Base URL / API Key，点「获取模型」拉列表选模型，保存。配置会热生效并 upsert 写进项目根 `.env`。

**方式 B — 编辑 `.env`**，重启后端。

**方式 C — 环境变量**，启动前 export。

预设参考（`backend/.env.example` 内已列）：

| 提供方 | Base URL | 备注 |
|---|---|---|
| 硅基流动 | `https://api.siliconflow.cn/v1` | 有免费额度 |
| 智谱 BigModel | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` 免费 |
| Ollama | `http://localhost:11434/v1` | 完全离线，key 填 `ollama` |

> **多 worker 下改配置只有当前 worker 热生效**，其余 worker 靠 `.env` 在重启后对齐。生产环境改完 LLM 配置请重启服务。

### 3.4 Obsidian 服务端目录选择

Knowledge Hub 的“添加 Vault”浏览的是**后端所在机器**的目录，而不是浏览器所在电脑的目录。目录浏览、添加 Vault 和扫描属于文件系统管理能力：本机访问免管理令牌；从内网其它设备访问时，必须先在设置页输入 `ADMIN_TOKEN`。手动输入仍受支持，但必须填写后端机器上的绝对路径。

扫描结果保留 Vault 内的相对路径。前端默认将这些路径还原为可展开的目录树，也可切换到“最近修改”按文件修改时间倒序查看；搜索会匹配文件名、目录路径和标签，并自动展开匹配项的父目录。

### 3.5 数据目录「设一次忘掉」

在项目根创建 `.airos-data-dir` 文件，首行写数据目录绝对路径即可。优先级：

```
命令行 -DataDir  >  .airos-data-dir 文件  >  已有环境变量 DATA_DIR  >  <项目根>/data
```

---

## 4. 多人内网使用

1. 后端以 `APP_HOST=0.0.0.0` 启动；Windows 后台脚本固定单 worker，Linux/macOS 或交互式手动启动可按容量开 `--workers N`。
2. 同事访问 `http://<你的内网IP>:8000`（生产态）或 `:5173`（开发态，Vite 已 `host: true`）。
3. 首屏 `SpaceGate` 要求每人填写自己的**空间口令**（≥ 4 字符），此后所有数据按空间隔离。
4. 需要协作时，用顶栏空间指示器的「分享」生成 `?space=xxx` 链接发给对方，对方打开即自动进入同一空间。
5. 如需从其它设备进入设置、备份、SwanLab 或 Skills，请在后端 `.env` 配置至少 32 字符的 `ADMIN_TOKEN`，
   然后在设置页“系统管理访问”输入；令牌只保存在该浏览器标签页。

**边界说明**：

- 空间是**数据视图隔离，不是安全边界**——知道口令即可访问。仅适用于可信内网。
- LLM 配置、SwanLab 配置、Skills、备份是**全局共享**的，修改会影响所有人，因此远程访问受 `ADMIN_TOKEN` 保护。
- 不要把服务暴露到公网。

---

## 5. 数据备份与多设备同步

所有数据都在 `DATA_DIR`（默认 `<项目根>/data`），含 SQLite 库 `ai_research_os.db` 与 PDF / 记忆等文件。

### 5.1 方式一：数据目录指向同步盘（日常双设备首选）

后端通过 `DATA_DIR` 定位数据目录，目录不存在时自动建库建表，**无需改代码**：

```powershell
.\start.ps1 -DataDir D:\Sync\airos-data
```

```bash
./start.sh --data-dir ~/Sync/airos-data
```

配合 **Syncthing**（开源、去中心化、不绑云账号）在两台机器间实时同步该目录，即可实现「单数据源」，从根上消灭「哪边才是最新」的问题。步骤：两台都装 Syncthing → 添加同一个同步文件夹并互加设备 ID → 启动时把 `DATA_DIR` 指过去。

> ⚠️ **铁律：同一时刻只能有一台机器在写这个库。** SQLite 不支持多进程跨机并发写，两台同时写有损坏风险。离开工位前关掉那台的服务。
>
> 若已冲突（出现 `.sync-conflict-<时间戳>` 副本）：先停掉两台的服务 → 对比副本与原文件保留想要的那份 → 删除冲突副本 → 再启动其中一台。

同理适用于 OneDrive / iCloud / 坚果云，但实时性与冲突处理不如 Syncthing。

### 5.2 方式二：备份包导出 / 导入（换机最稳妥）

界面「设置 → 数据备份与迁移」：

- **导出**：整个 `DATA_DIR` 打包 zip 下载；SQLite 通过 Online Backup API 生成 WAL 一致性快照，自动剔除缓存、实例心跳及 `-wal` / `-shm` sidecar，附 `manifest.json`。
- **导入**：选择 zip，后端先完整校验并暂存，再把当前数据快照到 `<DATA_DIR 同级>/.backup-<时间戳>`；
  文件使用原子替换，任一步失败都会自动回滚并返回错误；若 Worker 被强制终止，下次启动会在数据库初始化前根据
  `.airos-backup-import.json` 自动恢复，不再产生部分成功。

```bash
curl -X POST http://localhost:8000/api/backup/export -o airos-backup.zip
curl -X POST http://localhost:8000/api/backup/import -F "file=@airos-backup.zip"
```

远程调用需额外添加 `-H "X-Admin-Token: $ADMIN_TOKEN"`。同一部署的导入和导出通过跨进程文件锁互斥。

> 导入是**整库覆盖、不合并**，会替换所有空间的数据。适合换机，不适合日常来回同步。

### 5.3 方式三：直接拷贝

停掉服务后整个 `data/` 目录拷走即可。WAL 模式下注意一并拷贝 `-wal` / `-shm` 文件，或先正常关闭服务让 WAL checkpoint 完成。

---

## 6. 故障排查

| 症状 | 排查方向 |
|---|---|
| 前端一直显示「离线」 | `curl http://localhost:8000/api/healthz`；检查后端是否起了、端口是否被占；Vite 代理目标 `VITE_API_TARGET` 是否正确 |
| 所有接口返回 400 `SPACE_REQUIRED` | 未填空间口令或口令 < 4 字符。清 localStorage 的 `ai-research-os-storage` 重新填 |
| Chat / 总结报 LLM 错误 | `curl http://localhost:8000/api/llm/status`；用「设置 → 测试连接」看具体 401/403/404/429 诊断 |
| `web_search` 所有检索源超时 | 查看 `app.<PID>.log` 中的 `skill.attempt`。确认代理端口确实在监听且同时配置 HTTP/HTTPS 代理；国内网络建议配置 `BOCHA_API_KEY`，避免只依赖 DuckDuckGo/Wikipedia |
| LLM 返回 404 | **Base URL 与 path 拼接重复**。确认 Base URL 自带 `/v1`，`LLM_HTTP_PATH` 只是 `/chat/completions` |
| 改了 LLM 配置不生效 | 多 worker 下只有一个 worker 热更新。重启服务 |
| `database is locked` | 检查是否两个进程/两台机器同时写同一个库；确认 WAL 生效（`PRAGMA journal_mode` 应为 wal） |
| Cron 任务没触发 | 检查 5 字段表达式或 daily/weekly/hourly；查看任务的 `enabled` / `nextRun` 与 `/api/cron/jobs/{id}/history`。多 Worker 使用旧 `next_run` 原子领取，某个 Worker 未领取通常表示另一个 Worker 已推进该次计划 |
| 手动 Cron 看似未改变计划时间 | 这是预期语义：立即执行会更新 `lastRun/runCount` 并写历史，但不推进原 `nextRun` |
| Agent run 卡在 running | 查 `agent_run_events` 最后一条事件；LLM 超时（默认 120s）会让阶段长时间无输出；可调 `POST /runs/{id}/cancel` |
| 中文乱码（PowerShell） | `.ps1` 必须是 **UTF-8 with BOM**，脚本头部需有 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` |
| PDF 预览空白 | pdf worker 走 cdnjs CDN，内网/离线不可用。需自托管 worker 文件 |
| 字体不对 | Google Fonts CDN 不可达，回退系统字体。离线需自托管 Manrope / Space Grotesk |
| 前端类型报错 | `cd frontend && npx tsc --noEmit` 看完整错误；本项目 `strict` + `noUnusedLocals` 全开 |

### 日志与探针

```bash
curl http://localhost:8000/api/healthz     # 版本 + DB 路径 + 是否存在
curl http://localhost:8000/api/llm/status  # LLM 配置与可达性（30s 缓存）
```

后端使用 Python 标准库 `logging` 保存长期日志，无需额外日志依赖。项目根目录
`logs/` 是唯一正式日志入口，`backend/logs/` 已永久废弃：

```text
logs/
├── launcher/                 # 启动器 stdout/stderr，10 MB 轮转、保留 5 份
│   ├── backend.log
│   ├── backend.err.log
│   ├── frontend.log
│   └── frontend.err.log
├── runtime/                  # 活跃 Worker 的独立 PID 日志
│   ├── app/app.<PID>.log
│   ├── access/access.<PID>.log
│   └── error/error.<PID>.log
├── archive/<日期>/<类别>/    # 已退出 Worker 的日志
└── state/                    # backend.pid / frontend.pid
```

- `<PID>` 隔离多 Worker 写入，避免 Windows 多进程竞争同一个轮转文件。
- `stop.ps1` 和 `start.sh` 停止服务后会把已退出 Worker 日志按日期归档。
- 启动时先迁移旧平铺日志，再按 `LOG_RETENTION_DAYS` 和 `LOG_MAX_FILES` 双重清理；活跃日志始终受保护。
- `python -m scripts.qa_verify_*` 自动使用系统临时日志目录，进程退出后删除，不污染正式日志。
- 每个 HTTP 响应携带 `X-Request-ID`，相同 ID 会进入应用日志，便于串联排障。
- 工具日志只记录工具名、参数字段名、检索源、耗时和状态，不记录 API Key 或完整请求内容。

统一查看命令会自动合并多个 PID 文件，无需人工寻找最新 Worker：

```powershell
# 最近 100 行应用日志
.\.venv\Scripts\python.exe -m scripts.log_view --kind app --lines 100

# 持续跟踪全部当前日志，并自动发现新 Worker
.\.venv\Scripts\python.exe -m scripts.log_view --kind all --follow

# 查询错误日志及历史归档
.\.venv\Scripts\python.exe -m scripts.log_view --kind error --include-archive --lines 200

# 手动执行归档与双重清理
.\.venv\Scripts\python.exe -m backend.server.core.log_maintenance prepare
```

---

## 7. 验收脚本

```powershell
# 空间隔离与管理边界（46 项）
python -m scripts.qa_verify_space

# 后端目录、公开入口与依赖方向
python -m scripts.qa_verify_backend_architecture

# 后台 Agent runner（19 项）
python -m scripts.qa_verify_agent_runner

# 正确性修复（论文旧库迁移、Cron 并发/API、公式、版本、RAG、CLI）
python -m scripts.qa_verify_correctness
python -m scripts.qa_verify_agent_teams       # 专家团队与 DAG（39 项）

# Python 语法与全部独立 QA（PowerShell）
python -m compileall -q backend scripts
Get-ChildItem scripts/qa_verify_*.py | ForEach-Object { python -m "scripts.$($_.BaseName)"; if ($LASTEXITCODE) { throw $_.Name } }
Get-ChildItem scripts/qa_verify_*.mjs | ForEach-Object { node $_.FullName; if ($LASTEXITCODE) { throw $_.Name } }

# 前端护栏
Push-Location frontend
npx tsc --noEmit
npm run lint
npm run build
Pop-Location
```

QA 脚本使用隔离的临时 `DATA_DIR` 或 mock，不会污染现有数据。包含 Unicode 符号的脚本会主动配置 UTF-8，可直接在 Windows 默认 PowerShell 中运行。需要 `aiosqlite / fastapi / httpx / uvicorn`。
