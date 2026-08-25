# 部署与运维

> 环境配置、启动方式、多人协作、数据备份、故障排查。核对日期：2026-07-30

---

## 1. 环境要求

| 工具 | 版本 | 必需 |
|---|---|---|
| Python | ≥ 3.10（实测 3.12 / 3.13） | 是 |
| Node.js | ≥ 22 | 是（仅前端） |
| Git | 任意 | 否 |

后端依赖仅 8 个包（`backend/requirements.txt`）：

```
fastapi>=0.110      uvicorn[standard]>=0.29   pydantic>=2.6
pydantic-settings>=2.2   python-dotenv>=1.0   requests>=2.31
python-multipart>=0.0.9  aiosqlite>=0.20
```

`requests` 只给 `scripts/formula_service.py` 用；`python-multipart` 给备份上传用；**没有 openai SDK**，LLM 客户端是标准库实现。

---

## 2. 启动

### 2.1 一键脚本（推荐）

```powershell
# Windows
.\start.ps1                      # 后端 :8000 + 前端 :5173
.\start.ps1 -SkipFrontend        # 仅后端
.\start.ps1 -SkipBackend         # 仅前端
.\start.ps1 -SkipLLM             # 跳过 LLM 可用性校验
.\start.ps1 -ApiPort 9000        # 自定义后端端口
.\start.ps1 -ApiWorkers 4        # worker 数；0 = 自动 min(CPU, 8)
.\start.ps1 -DataDir D:\Sync\airos-data   # 覆盖数据目录
```

```bash
# Linux / macOS
./start.sh
./start.sh --data-dir ~/Sync/airos-data
```

脚本首次运行会在项目根创建 `.venv` 并把后端依赖装进去，**不污染系统全局 Python**（仅创建 venv 那一刻用全局解释器）。

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
| `CONTEXT_TOKEN_LIMIT` | `16000` | Chat 上下文压缩阈值 |
| `DB_PATH` | 无 | 直接指定 DB 文件，优先级高于 `DATA_DIR` |
| `DATA_DIR` | `<项目根>/data` | 数据目录，脚本与文件归档均以此为根 |
| `APP_HOST` | `0.0.0.0` | |
| `APP_PORT` | `8000` | |
| `CORS_ORIGINS` | `*` | 逗号分隔；为 `*` 时自动关闭 credentials |

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

### 3.4 数据目录「设一次忘掉」

在项目根创建 `.airos-data-dir` 文件，首行写数据目录绝对路径即可。优先级：

```
命令行 -DataDir  >  .airos-data-dir 文件  >  已有环境变量 DATA_DIR  >  <项目根>/data
```

---

## 4. 多人内网使用

1. 后端以 `APP_HOST=0.0.0.0` 启动（`start.ps1` 默认已是），开 `--workers N`。
2. 同事访问 `http://<你的内网IP>:8000`（生产态）或 `:5173`（开发态，Vite 已 `host: true`）。
3. 首屏 `SpaceGate` 要求每人填写自己的**空间口令**（≥ 4 字符），此后所有数据按空间隔离。
4. 需要协作时，用顶栏空间指示器的「分享」生成 `?space=xxx` 链接发给对方，对方打开即自动进入同一空间。

**边界说明**：

- 空间是**数据视图隔离，不是安全边界**——知道口令即可访问。仅适用于可信内网。
- LLM 配置、SwanLab 配置、Skills、备份是**全局共享**的，任何人改都影响所有人。
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

- **导出**：整个 `DATA_DIR` 打包 zip 下载，自动剔除 `.git` / `.swanlab` / `.cache` / `__pycache__`，附 `manifest.json`。
- **导入**：选择 zip，后端**先自动把当前数据备份到 `<DATA_DIR 同级>/.backup-<时间戳>`**，再覆盖。若应用正占用数据库导致写入失败，响应里会给出明确提示，此时停掉服务重新导入。

```bash
curl -X POST http://localhost:8000/api/backup/export -o airos-backup.zip
curl -X POST http://localhost:8000/api/backup/import -F "file=@airos-backup.zip"
```

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
| LLM 返回 404 | **Base URL 与 path 拼接重复**。确认 Base URL 自带 `/v1`，`LLM_HTTP_PATH` 只是 `/chat/completions` |
| 改了 LLM 配置不生效 | 多 worker 下只有一个 worker 热更新。重启服务 |
| `database is locked` | 检查是否两个进程/两台机器同时写同一个库；确认 WAL 生效（`PRAGMA journal_mode` 应为 wal） |
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

uvicorn 日志直接输出到启动终端，无独立日志文件。

---

## 7. 验收脚本

```bash
# 空间隔离（26 项）
python scripts/qa_verify_space.py

# 后台 Agent runner（19 项）
python scripts/qa_verify_agent_runner.py

# 前端护栏
cd frontend && npx tsc --noEmit && npm run build && npm run lint
```

两个 QA 脚本使用隔离的临时 `DATA_DIR`，不会污染现有数据。需要 `aiosqlite / fastapi / httpx / uvicorn`。
