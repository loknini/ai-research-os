# 技术债清单

> 最近核对：2026-09-17；初始审计基线 `dd6a4dd`，T11/T13/T14 在其后核销。
>
> 本清单只保留当前仍存在的债务。表/路由/Hub 等架构数字仍以
> [`_meta.json`](./_meta.json) 为事实源；本文中的行数和调用点数量只是本次审计快照。
>
> 优先级：🔴 高（安全、数据正确性）· 🟡 中（可维护性、测试、性能）· 🟢 低。

---

## 🔴 高优先级

*无。* T13 管理访问边界与 T14 备份事务化已于本轮完成，并由远程拒绝/令牌放行、故障注入回滚与 SQLite 完整性测试覆盖。

---

## 🟡 中优先级

### T10. 无统一测试框架与 CI 门禁

- **现状**：没有 `tests/`、`frontend/tests/`、`backend/tests/`、`.github/workflows/`、`pytest.ini` 或 Vitest 配置；
  `frontend/package.json` 没有 `test` 脚本。当前有 27 个 `scripts/qa_verify_*` 脚本，仍依赖人工选择和执行。
- **补充问题**：RAG 黄金集门禁未接入自动流程；`eval_rag_golden.py` 使用手写 `sys.argv`，未知命令和 `--help`
  会落入评测执行路径。黄金集由当前业务数据合成，适合作为回归基线，但不能替代独立人工标注集。
- **影响**：数据库迁移、多 Worker 抢锁、空间隔离、备份恢复、向量代际切换等关键回归容易漏跑；不同脚本的退出码和夹具纪律难统一。
- **建议**：逐步迁入 `pytest`/Vitest，先建立一个调用现有脚本的统一 `test` 入口，再接入 GitHub Actions；
  所有测试继续使用独立 `DATA_DIR`，RAG 门禁增加固定、评审过的脱敏夹具。
- **验收**：一条后端命令和一条前端命令可跑完核心回归；CI 对失败返回非零并阻止合并；测试不读写真实用户数据。

### T12. 前端 Hub 巨石，API 客户端统一尚未落地

- **现状**：`ChatHub.tsx` 约 1835 行、`settings/index.tsx` 约 1484 行；当前有 14 个 Hub 范围内的 TS/TSX 文件超过 400 行，
  `any` 约 89 处。虽然已抽出部分 Chat 组件和服务，但侧边栏、消息列表、输入、RAG 选择与流程状态仍集中在 `ChatHub`。
- **API 现状**：`frontend/src/services/api.ts` 定义了 `apiFetch`，当前业务调用点为 0；前端仍约有 132 个直接 `fetch()` 调用。
  `X-Space-Key` 主要依赖 `apiMonitor.ts` 对全局 `fetch` 的 monkey patch 注入，错误解析、超时和响应类型没有真正统一。
- **影响**：页面状态和网络副作用难隔离测试；不同模块的错误处理不一致；全局 monkey patch 隐式改变第三方或未来请求行为。
- **建议**：先让新代码只使用统一客户端，再按 Hub 迁移；为 SSE、文件下载和普通 JSON 请求提供明确的客户端适配层；
  续拆 `ChatSidebar`、`MessageList`、`InputBar`、RAG source selector，并用 `unknown` + 类型守卫替代边界层 `any`。
- **验收**：除统一客户端内部及明确豁免的流式/下载适配器外，不再直接调用 `fetch`；移除全局 monkey patch 后功能和空间隔离测试仍通过。

### T15. 正规包导入约定未完全落实

- **现状**：`backend/` 与 `scripts/` 已是正规包，但仓库仍有约 31 处 `sys.path.insert/append`；其中 4 处位于正式业务脚本：
  `fetch_arxiv.py`、`citation_service.py`、`formula_service.py`、`summarize_paper.py`，其余主要分布在 QA、评测和回填脚本。
- **影响**：模块执行与文件直跑可能加载不同模块，遮蔽导入错误；测试环境与生产启动方式不一致。
- **建议**：业务入口统一使用 `python -m scripts.<module>` 和 `from scripts import database`；QA 由统一测试入口提供项目根路径，删除脚本内注入。
- **验收**：业务代码无 `sys.path` 修改；模块方式和受支持的 CLI 入口均通过；错误启动方式给出明确用法提示。

---

## 🟢 低优先级

### T16. 小型结构与文档漂移

- `frontend/src/hubs/knowledge/KnowledgeHub.tsx:578` 仍有“打开 Obsidian 文件详情”的未实现 TODO。
- `backend/requirements.txt` 中 `requests` 仅由 `scripts/formula_service.py` 使用；可移入专用依赖文件，或注明它属于公式 OCR 子进程。
- `vite.config.ts.timestamp-*.mjs`（当前 6 个）与 `frontend/dist-verify` 已由 `.gitignore` 忽略，但本地仍有残留；不影响仓库存量。

---

## 已核销与重新打开说明

已验证仍可核销：T1 `mask_key` 重复、T2 PDF worker CDN、T3 Agent 旧端点、T4 暗色开关、
T5 `frontend/api-server.js` / `pdf-lib` 死代码、T6 原伪债、T7 路由懒加载/404、T8 `version` 遮蔽，
以及 Chat 路由强制空间依赖、LLM 客户端去重、RAG 全量向量扫描治理、关键复合索引和 ChatHub 首轮拆分。

本次重新打开或纠正：

- 原 T9“无 `sys.path` 注入”不符合当前代码，改列为 T15。
- “`apiFetch` 已统一”不符合当前调用实况，合并进 T12。
- “backup 全租户泄露已修复”实际只是把接口明确为全局能力；访问控制问题改列为 T13。

本轮新增核销：T11 已拆为 `db/core.py`、版本化 `db/migrations/` 与领域 `db/repos/`，
`database.py` 缩为兼容门面；`schema_migrations` 记录版本、名称、校验和、时间与耗时，迁移由跨进程锁串行执行，
并新增幂等、历史篡改、未来版本拒绝和事务回滚测试。T13 已通过“本机免登录、远程 `ADMIN_TOKEN`”管理边界解决；
T14 已通过同盘完整暂存、原子替换、跨 Worker 互斥、持久导入日志和失败/崩溃自动恢复解决。

历史治理提交可参考 `5c03c5a`、`26ecf0e`；RAG 2.1 与本次初始审计基线为 `dd6a4dd`。
