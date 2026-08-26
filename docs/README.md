# 文档索引（docs/）

本目录集中存放 AI-Research-OS 的**架构与设计文档**。所有内容均基于代码实况整理（最近一次大规模重构：2026-07-30）。

> 过时/冗余的旧文档已移入仓库根目录的 `.archive/docs-legacy-20260730/`（gitignored）。确认无用后可将整目录删除。

## 阅读顺序建议

- **第一次了解项目** → 先读 `ARCHITECTURE.md`（全局定位与分层），再按需深入。
- **要接后端接口** → 直接查 `API.md`（路由表 + 流式协议 + curl）。
- **要做数据相关改动** → 查 `DATA-MODEL.md`（表结构 + space-key 隔离 + 更新语义）。
- **要动 LLM / Agent / Skills** → 查 `AGENT-LLM.md`（含模块导入约定，务必先读）。
- **要动前端** → 查 `FRONTEND.md`（技术栈 + 路由 + 状态 + 设计系统）。
- **要部署 / 排障 / 备份** → 查 `OPERATIONS.md`。
- **想清理技术债** → 查 `TECH-DEBT.md`。

## 文档清单

| 文档 | 主题 | 关键内容 |
|------|------|----------|
| [SYSTEM-DESIGN.md](./SYSTEM-DESIGN.md) | 系统设计文档 | 一页看懂式综合设计：分层架构图（mermaid）、核心模块速览（前端/后端横切/LLM 客户端/Agent 体系/RAG/Cron/数据层）、四条核心数据流（CRUD / Chat ReAct+RAG / Agent 后台管线 / Cron）、关键设计决策表（2026-08-24 核对） |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 系统架构 | 三条硬约束（本地优先/零重依赖/不登录多人可用）、进程模型、分层结构、请求生命周期（CRUD / Chat ReAct / Agent 后台）、关键架构决策、外部依赖表、部署形态 |
| [DATA-MODEL.md](./DATA-MODEL.md) | 数据模型 | SQLite WAL 与连接管理、space-key 软隔离模型与迁移、26 张业务表、`database.py` 函数分组、更新语义（`rowcount>0`）、QA 验收脚本 |
| [API.md](./API.md) | 接口契约 | 通用约定（X-Space-Key / 响应体 / camelCase）、113 条 `/api/*` 路由按 21 个 router 分表、SSE 帧格式、curl 速查 |
| [AGENT-LLM.md](./AGENT-LLM.md) | LLM 与 Agent | urllib LLM 客户端（URL 拼接/function calling/降级）、Chat ReAct 循环、角色化 Agent 管线、`agent_runner` 双层取消、Skills 目录约定与安全边界、模块导入约定（正规包导入，无 sys.path hack） |
| [FRONTEND.md](./FRONTEND.md) | 前端 | 技术栈（含刻意不引入的库）、vite proxy、11 路由表、App 组件层次、barrel 拆分现状与新增 Hub 标准、状态管理、API 层（两套流式协议）、设计系统、验证护栏 |
| [OPERATIONS.md](./OPERATIONS.md) | 运维 | 环境要求、启动方式（start.ps1/-sh 参数 / 手动 / 生产单进程托管）、配置加载顺序与变量清单、多人内网使用、数据备份三种方式、故障排查、验收脚本 |
| [TECH-DEBT.md](./TECH-DEBT.md) | 技术债 | 已确认死代码与兼容层、已关闭误报项，以及版本详情遮蔽等已修复问题的审计记录 |

## 与根目录文档的关系

- `README.md` — 面向人类用户的项目说明（安装 / 运行 / 使用示例 / 故障排查），侧重"怎么用"。
- `AGENTS.md` — 面向 AI 协作者，概览 + 开发规范 + 模块导入约定，侧重"怎么改"。
- `CHANGELOG.md` — 里程碑式版本变更记录。

## 约定

- 所有接口路径以 `/api` 前缀书写（如 `/api/papers/fetch`）。
- 空间隔离通过请求头 `X-Space-Key` 传递，由后端处理器级依赖 `get_space_id` 解析，不依赖中间件。
- LLM 调用一律走 `backend/server/llm.py`，**禁止引入 `openai` SDK**。
