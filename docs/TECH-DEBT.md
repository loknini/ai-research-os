# 技术债清单

> 最近核对：2026-09-30。
>
> 本文件只记录当前仍需处理的事项；已核销的 T1–T16 及审计纠正记录已移入
> [`CHANGELOG.md`](../CHANGELOG.md)。表、路由和 Hub 等架构数字以
> [`_meta.json`](./_meta.json) 为事实源。

## GitHub required check 尚待启用

- **现状**：`.github/workflows/ci.yml` 已在 Pull Request 与 `main` push 时执行前端
  `npm run verify` 和后端完整 pytest，并上传 JUnit 报告。
- **缺口**：工作流失败会显示红灯，但只有仓库管理员在 GitHub
  `Settings → Rules → Rulesets` 中为 `main` 启用 “Require status checks to pass”，并选择
  `Frontend and backend verification`，才能禁止绕过失败检查直接合并。
- **验收**：创建一个故意使测试失败的临时 Pull Request，确认合并按钮被禁用；测试恢复后，检查通过且允许合并。

## T17. 历史隔离 case 与 RAG 黄金集仍可继续产品化

- **优先级**：低。
- **现状**：Chat 工具循环和 LLM 状态已经迁为原生 pytest；其余复杂的 SQLite、多进程和 RAG
  回归仍保留在 `tests/backend/_cases/`，由共享 fixture 隔离执行。RAG 黄金集 CLI 已改用 argparse，
  但语料仍由本机业务数据合成，没有可提交、经人工评审且脱敏的独立基准集。
- **影响**：不影响 CI 门禁和回归正确性，但历史 case 的报告粒度较粗，RAG 检索质量也暂时不适合在
  公共 CI 中作为稳定阈值门禁。
- **建议**：按修改频率逐域原生化剩余 case；另行建立版本化、脱敏、人工评审的 RAG 固定语料后，
  再把 `eval_rag_golden gate` 加入 CI。
- **验收**：`_cases/` 归零或仅保留确需进程隔离的场景；固定黄金集具备来源、评审和版本记录，
  在无用户数据库、无外部 LLM 的环境中可重复通过。
