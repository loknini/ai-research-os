# 后端代码结构

## 分层方向

后端采用“薄入口 + 领域包 + HTTP 路由”的结构，公开启动入口始终保持为
`backend.server.main:app`。重构只调整 Python 模块归属，不改变 API 路径、响应结构、
数据库迁移、space-key 隔离或工具协议。

依赖方向固定为：

```text
routers → domains/services → db、llm、文件系统等基础设施
                     ↓
                   core
```

`core`、领域包和服务层禁止反向导入 `routers`。`scripts/database.py` 及
`scripts/db/repos/` 仍是数据库持久层真身，不把 SQL 搬回 HTTP 或领域模块。

## 目录职责

| 目录/模块 | 职责 |
|---|---|
| `main.py` | 创建 FastAPI 应用、装配中间件与路由 |
| `core/` | 配置、日志、异常、安全边界、健康检查和应用生命周期 |
| `rag/` | 文档处理、嵌入、索引、检索及后台任务 |
| `agents/` | 角色执行、专家团队校验及后台运行 |
| `development/` | 软件研发工作区和后台执行器 |
| `services/` | 备份、设置等不应放在路由中的应用服务 |
| `routers/` | 参数校验、权限依赖和 HTTP 响应映射 |
| `tools/` | Agent 工具实现与自动发现 |

## 正式导入路径

RAG、Agent、研发运行器与核心设施分别从 `backend.server.rag`、
`backend.server.agents`、`backend.server.development`、`backend.server.core` 导入。
历史根级兼容模块已在仓库内调用方全部迁移后删除，不再维护双入口。Agent CLI 保留在
`python -m backend.server.agents.service`。

## 结构回归

运行：

```powershell
pytest tests/backend/infrastructure/test_imports.py -k backend-architecture
```

该测试验证公开入口、项目根目录解析、路由聚合、正式模块导入、退役模块不存在、内置
Agent 资源、工具发现、`sys.path` 约束和“领域层不得依赖路由层”的依赖方向；同时限制
`main.py` 与薄路由的行数，防止业务逻辑重新回流。
