# 技术债清单

> 严格对照代码重审（2026-09-02）。已解决项已删除，仅保留当前仍存在的债务；历史已解决记录见 Git `5c03c5a` / `26ecf0e`。
> 优先级：🔴 高（正确性/安全）· 🟡 中（可维护/性能）· 🟢 低。

---

## 🔴 高优先级

*无。* 上次扫描的高优债务（`mask_key` 两套、`PDF CDN`、`Agent旧端点`、`chat隔离旁路`、`LLM三处重复`、`RAG全量加载OOM`、`backup全租户泄露`）均已在 `26ecf0e` 中修复并验证（`py_compile` / `npm lint/build` 通过）。

---

## 🟡 中优先级

### T10. 无统一测试框架与 CI

- **现状**：无 `tests/`、`frontend/tests/`、`backend/tests/`、`.github/workflows/`、`pytest.ini` / `vitest.config`；`package.json` 无 `test` 脚本；校验仍靠 `qa_verify_*.py/.mjs` 14+3 脚本手工执行（`TECH-DEBT` 原 T10）。
- **影响**：并发迁移、多 Worker 抢锁等回归仅靠人肉，易漏。
- **建议**：收敛 `qa_verify_*` 为 `pytest`/`vitest` 统一入口，接入 GitHub Actions 门禁；保留 `DATA_DIR` 隔离纪律。

### T11. `scripts/database.py` 单文件巨石

- **位置**：`scripts/database.py:1` 3864行，`init_db:134` 700行，80+ 函数。
- **影响**：改一处即全量失效风险，难以单测；虽已补 7 个复合索引（`idx_tasks_space_project` 等 `database.py:334,401`），但结构仍单体。
- **建议**：按域拆 `db/core.py`（`get_db/init_db`）、`db/tables/*.py`（DDL）、`db/repos/*.py`（CRUD），`database.py` 仅作兼容 re-export。

### T12. 前端 Hub 单文件巨石

- **位置**：`hubs/chat/ChatHub.tsx:1` 1500行、`hubs/settings/index.tsx:1067` 等 9 个 Hub >400行（`frontend/src/hubs`）。
- **现状**：已抽 `hubs/chat/components/ReasoningPanel.tsx` / `RagCitations.tsx` / `hooks/useChatState.ts` 并新增 `services/api.ts` 统一 `apiFetch`、`App.tsx:92` 每路由 `ErrorBoundary`，但 `ChatHub` 仍承载侧边栏/消息列表/输入等全量逻辑。
- **建议**：续拆 `ChatSidebar/MessageList/InputBar`，其余 Hub 按 `barrel` 标准（`config/types/hooks/services/components`）补齐；全量 `any`（69处）收敛为 `unknown`+`zod` 校验。

---

## 🟢 低优先级

- `vite.config.ts.timestamp-*.mjs`（6个）与 `frontend/dist-verify` 等为 `.gitignore` 已忽略的本地产物，磁盘残留但不入库存量，无需处理。
- `backend/requirements.txt:13` `requests` 仅 `scripts/formula_service.py:6` 子进程使用，属跨层声明，可移 `scripts/requirements-formula.txt` 或注释说明。

---

## 已归档

本轮已核销并删除的条目：T1 `mask_key`、T2 `PDF worker CDN`、T3 `Agent旧端点`、T4 `暗色开关`、T5 `死代码/api-server.js/pdf-lib`、T6 `伪债`、T7 `懒加载/404`、T8 `version遮蔽`、T9 `sys.path hack`，以及 7 项专项治理（`chat Depends`、`LLM去重`、`RAG LIMIT 3000`、复合索引、`apiFetch`、`ChatHub初拆`）。详见提交 `5c03c5a` / `26ecf0e`。
