# 技术债清单（TECH-DEBT）

> 本文记录 AI-Research-OS 中**已知但暂未清理**的技术债与重复实现。优先级分三档：
> 🔴 高（有正确性或稳定性风险）· 🟡 中（维护成本 / 一致性）· 🟢 低（体验 / 收尾）。
> 标记为「待核查」的项基于代码走查推测，落地前请先确认。

---

## 🔴 高优先级

### ~~T1. `mask_key` 两套不一致~~ ✅ 已解决（2026-07-30）
**状态：已解决。** 新建 `backend/server/utils.py:mask_key` 为唯一实现；`llm.py`/`settings.py`/`health.py` 统一调用，删除旧重复。验证：`py_compile` 通过，grep 确认零 `_mask_key` 残留。
- **位置**：`backend/server/llm.py:234` `_mask_key`（方法）与 `backend/server/routers/settings.py:63` `_mask_key`（模块函数）。
- **问题**：两处逻辑不一致：
  - `llm.py`：长度 ≤6 全 `*`；否则 `key[:3] + "*"*(len-6) + key[-3:]`（首尾各留 3 位，星号数随长度变化）。
  - `settings.py`：先 `strip()`，长度 ≤8 全 `*`；否则 `key[:4] + "*"*6 + key[-4:]`（首尾各留 4 位，固定 6 颗星）。
- **影响**：同一 API Key 在 `/api/llm/status` 与 `/api/settings` 返回的代表符**形态不同**，排查与审计时易误判；且 `settings.py` 多了一次 `strip()`，对带空格的 Key 脱敏结果也不同。
- **建议**：收敛为单一实现（放 `llm.py` 或 `utils`），两处统一调用。

### ~~T2. PDF worker 走 CDN~~ ✅ 已解决（2026-07-30）
**状态：已解决。** `frontend/src/components/ui/pdf-viewer.tsx` 改为从 `pdfjs-dist/build/pdf.worker.min.mjs?url` 经 Vite 本地打包（并显式把 `pdfjs-dist@5.4.296` 加入 `package.json` 依赖）；`npm run build` 通过，worker 已打入 `dist/assets`。
- **位置**：`frontend/src/components/ui/pdf-viewer.tsx:8`
  ```ts
  pdfjs.GlobalWorkerOptions.workerSrc =
    `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`
  ```
- **问题**：论文 PDF 预览依赖外网 CDN 拉取 `pdf.worker.min.js`。内网 / 离线环境（本项目主要场景）下 worker 加载失败，PDF 无法渲染。
- **建议**：把 worker 文件随构建打包（Vite `?url` 引入 `pdfjs-dist/build/pdf.worker.min.mjs`），改本地路径；或至少失败时给出明确降级提示。

---

## 🟡 中优先级

### ~~T3. 新旧 Agent 接口共存~~ ✅ 已解决（2026-07-31）
**状态：已彻底移除旧端点。** 用户确认无调用方后，`routers/agent.py` 的 `/api/agent/run` 与 `/api/agent/collaborate` 两个遗留一次性 SSE 端点已**整体删除**（连同仅服务于它们的 `import agent_service`、`LLMUnavailableError` 依赖）。
- **连带修复（与 T6 同源）**：前端唯一活调用方 `frontend/src/services/aiAgent.ts`（浮动聊天面板的命令/工具分发器）第 368 行曾把未匹配意图回退到 `/api/agent/run`；已改为优雅降级提示「复杂任务请到 Agent 面板处理」，不再依赖已删端点。
- **保留**：新前端走后台模式 `POST /api/agent/runs` + `GET /api/agent/runs/{id}/stream` + `POST .../cancel`（`agent_runner.py` 线程 + 自建事件循环）。
- **验证**：`py_compile` 全绿；`backend.server.main` app 加载正常（20 个 router 全部挂载）；`qa_verify_agent_runner.py` 实测 `POST /api/agent/runs → 200`；`npm run build` 前端构建通过（`aiAgent.ts` 改动编译无误）。

### ~~T4. 暗色主题 token 完备但无切换开关~~ ✅ 已解决（2026-07-30）
**状态：已解决。** 新建 `frontend/src/stores/themeStore.ts`（zustand，持久化到 localStorage，初值随 `prefers-color-scheme`）+ `frontend/src/components/layout/theme-toggle.tsx`（侧栏底部切换控件）；`main.tsx` 首屏渲染前 `applyTheme()` 防闪烁，`App.tsx` 注入 `ThemeSync` 组件，切 `<html>` 的 `dark` 类切换整套 token（Apple Light ⇄ Pro Graphite）。验证：`npm run build` 通过（`tsc` 零类型错误）。
- **原状**：`index.css` / `tailwind.config.js` 已定义完整暗色 token，但无切换入口，默认一直浅色。
- **改动文件**：`themeStore.ts`、`theme-toggle.tsx`、`not-found.tsx`（同批）、`main.tsx`、`App.tsx`、`sidebar.tsx`。

### T5. 死代码残留（部分已解决）
**状态：主体已归档，仍有一项待处理。** `scripts/db_api.py`、`scripts/workflow_engine.py`、`frontend/src/components/ui/tag-system.tsx`、`frontend/src/utils/performance.ts` 已于 2026-07-30 移入 `.archive/dead-code-20260730/`（保留原目录结构）。归档前 grep 确认零外部引用。
已确认仍存在、且无可达调用路径的文件：
- `scripts/db_api.py` —— 旧 CLI 数据库 API（`README` 旧示例曾引用，已移除引用；无路由调用）。
- `scripts/workflow_engine.py` —— 早期工作流引擎，被角色化 `agent_service.py` 取代。
- `frontend/src/components/ui/tag-system.tsx` —— 旧标签系统组件，已被各 Hub 内聚的标签实现取代。
- `frontend/src/utils/performance.ts` —— 性能工具，无引用。
> 当前仍有 `frontend/api-server.js`（注意不在 `src/` 下），全仓无运行时引用，是迁移到 FastAPI 前的旧中间件实现，尚待删除或归档。
- **建议**：删除前先全局 grep 确认零引用；删除后在 `CHANGELOG` 记一笔。项目已有 Git，仍可沿用 `.archive/` 保存需要人工复核的历史材料。

### ~~T6. 重复聊天 / Agent 实现并存~~ ✅ 已核查，伪债关闭（2026-07-31）
**状态：经细查确认非真实债务，关闭。**
- **核查方法**：全仓流式解析点主要有 2 处且分属不同功能——`hubs/chat/services/chatApi.ts` 与 `components/agent/agent-workflow.tsx`。两者当前都接收 SSE，但事件模型不同（Chat 文本/工具/RAG；Agent 阶段/审批/重放），不宜为了表面协议一致而强行合并状态机。
- **"两套聊天实现"误判来源**：旧式 `services/aiAgent.ts` 曾是浮动面板的命令/工具分发器，会回退调用 `/api/agent/run`（即 T3 旧端点）。它**从不实现第二套聊天流**，只是旧式委托。T3 删除旧端点后，`aiAgent.ts` 已改为本地工具分发 + 优雅降级，不再依赖后端 Agent 端点，与 `chatApi.ts` 无协议重叠。
- **结论**：无重复流式协议实现，无需统一抽象；T6 关闭。

---

## 🟢 低优先级

### ~~T7. 路由未懒加载、无 404 兜底~~ ✅ 已解决（2026-07-30）
**状态：已解决。** `App.tsx` 11 个 Hub 全部改为 `React.lazy` + `<Suspense fallback={<RouteFallback/>}>`，并新增美观的 `not-found.tsx`（渐变玻璃卡片 + 返回首页 CTA）作为 `path="*"` 通配兜底；`main.tsx` 内 `applyTheme` 已在首屏应用。`npm run build` 输出大量独立 `index-*.js` 小块，代码分割生效。改动文件：`App.tsx`、`not-found.tsx`、`main.tsx`。

### ~~T8. 版本历史路由与「版本」语义潜在遮蔽~~ ✅ 已核查，无问题（2026-07-30）
**状态：核查结论——无需改动。** 全仓唯一 version 相关路由是 `backend/server/routers/versions.py` 的 `APIRouter(prefix="/api/versions")`（**复数**前缀），业务路由为 `/api/versions` 及 `/api/versions/{id}`。**不存在单数 `/version` 字面路由**，也没有更宽前缀会吞掉它，早期探索报告的"version 路由遮蔽"在当前代码里不成立。沿用复数 `/versions` 命名即可，结论归档备查。

### ~~T9. 相对导入陷阱~~ ✅ 已彻底解决（2026-07-31）
**状态：已根除 `sys.path` 注入 hack，改为正规包导入。**
- **根因**：`backend/server/__init__.py` 曾把 `backend/scripts` 插到 `sys.path` 最前，使模块须用 `import agent_service` 式裸导入，且 `from .. import x` 会跳到顶层 `backend` 包报错（导入陷阱）。
- **彻底解法**：
  1. 新建 `scripts/__init__.py` 使顶层 `scripts` 成为正规包；将 `backend/scripts/agent_service.py` **移入 `backend/server/agent_service.py`**（彻底消除 `backend/` 内与顶层同名的 `scripts` 包遮蔽问题），删除 `backend/scripts/` 目录。
  2. 后端改正规绝对/相对包导入：`db.py`→`from scripts import database`、`papers.py`→`from scripts import fetch_arxiv` / `from scripts.summarize_paper import ...`、`chat.py`/`skills.py`→`from scripts.chat_agent_stream import ...`、`agent_runner.py`→`from . import agent_service`、`agent_service.py`→`from backend.server.llm import llm_client`。
  3. `backend/server/__init__.py` 删除全部 `sys.path` 注入，仅保留包说明文档。
  4. QA 脚本同步：`qa_verify_space.py` 仅把项目根加入 `sys.path`（**不再加 `backend/`**，否则 `import scripts` 会被 `backend/scripts` 遮蔽——该目录现已不存在，隐患根除）；`qa_verify_agent_runner.py` 改 `from backend.server import agent_service`。
- **验证（关键）**：两套隔离 QA 全绿——`qa_verify_space.py` **26/26 ALL_PASS**、`qa_verify_agent_runner.py` **19/0 PASS**；`py_compile` 全绿；`backend.server.main` app 加载正常；前端 `npm run build` 通过。DB 路径隔离（`DB_PATH` 覆盖）在改用包导入后**仍然有效**（后端与 QA 共享同一 `scripts.database` 模块对象），真实库未被污染。

### T10. 无统一测试框架与 CI（流程债）
- **现状**：项目已初始化 Git，但尚未接入 pytest/vitest 与 CI；当前验证靠 `tsc --noEmit`、构建和隔离 `DATA_DIR` 的 `qa_verify_*.py` / `.mjs` 脚本。
- **建议**：逐步把 QA 脚本收敛为统一测试入口并接入 CI，保留外部 API 打桩与临时数据目录纪律。

---

## 收尾建议（一次性清理 checklist）
1. [x] 收敛 `mask_key`（T1）— 2026-07-30 已解决。
2. [x] PDF worker 改本地打包（T2）— 2026-07-30 已解决。
3. [x] 删除旧 Agent 端点 `/run`、`/collaborate` + 修活调用方 `aiAgent.ts`（T3）— 2026-07-31 已彻底移除。
4. [x] 暗色切换开关（T4）— 2026-07-30 已解决。
5. [ ] 归档或删除剩余的 `frontend/api-server.js`（T5；其余旧实现已于 2026-07-30 归档）。
6. [x] 细查前端流式协议，确认为伪债关闭（T6）— 2026-07-31 已核查关闭。
7. [x] 补 404 + 懒加载（T7）— 2026-07-30 已解决。
8. [x] 核查 version 路由命名（T8）— 2026-07-30 核查无问题，关闭。
9. [x] 彻底消除 `sys.path` 导入 hack，改正规包导入（T9）— 2026-07-31 已解决。
10. [ ] 固化 QA 脚本为统一测试入口并接入 CI（T10；Git 已完成）。
