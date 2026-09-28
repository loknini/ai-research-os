# 技术债清单

> 最近核对：2026-09-28；初始审计基线 `dd6a4dd`，T11/T13/T14 在其后核销。
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

- **现状**：前端已为统一 HTTP transport 引入 Vitest 与 `npm test`，但仓库仍没有统一的后端测试入口、
  `.github/workflows/` 或 `pytest.ini`。当前 25 个 `scripts/qa_verify_*` 脚本仍依赖人工选择和执行。
- **补充问题**：RAG 黄金集门禁未接入自动流程；`eval_rag_golden.py` 使用手写 `sys.argv`，未知命令和 `--help`
  会落入评测执行路径。黄金集由当前业务数据合成，适合作为回归基线，但不能替代独立人工标注集。
- **影响**：数据库迁移、多 Worker 抢锁、空间隔离、备份恢复、向量代际切换等关键回归容易漏跑；不同脚本的退出码和夹具纪律难统一。
- **建议**：逐步迁入 `pytest`/Vitest，先建立一个调用现有脚本的统一 `test` 入口，再接入 GitHub Actions；
  所有测试继续使用独立 `DATA_DIR`，RAG 门禁增加固定、评审过的脱敏夹具。
- **验收**：一条后端命令和一条前端命令可跑完核心回归；CI 对失败返回非零并阻止合并；测试不读写真实用户数据。

---

## 🟢 低优先级

*无。* T16 的 Obsidian 文件详情、依赖归属、临时产物与文档漂移已完成清理。

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
T12 已建立唯一 HTTP transport（空间键、管理员令牌、连接状态、错误、超时、JSON/FormData/Blob/SSE），
删除全局 `fetch` monkey patch，并将 Chat 的侧栏、顶部控制、消息列表、输入区和消息渲染，以及 Settings 的通用、集成、扩展、RAG 面板拆开；
`ChatHub.tsx` 与 `settings/index.tsx` 已缩为编排入口。ESLint 与 `check:architecture` 会阻止业务代码重新直接调用 `fetch` 或入口文件重新膨胀。
T15 已移除业务、QA、评测与回填脚本中的 `sys.path` 注入；后端子进程统一通过项目根目录下的
`python -m scripts.<module>` 启动，不再设置 `PYTHONPATH`。README、运维文档和内置 Skill 命令已同步为模块入口，
公开 CLI 被错误地按文件执行时会给出明确的正确命令提示。
T16 已接通 Obsidian 文件详情读取与 Markdown/元数据预览，明确 `requests` 是 Formula Hub 的 SimpleTex OCR 运行时依赖，
清理本地 Vite 时间戳与 `dist-verify` 残留，并同步 API transport、前端结构和验证方式等文档。

历史治理提交可参考 `5c03c5a`、`26ecf0e`；RAG 2.1 与本次初始审计基线为 `dd6a4dd`。
