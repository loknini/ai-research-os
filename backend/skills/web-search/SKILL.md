---
name: web_search
description: 通用联网搜索。返回标题、摘要、来源链接与发布时间，用于获取最新资讯、技术文档、竞品信息、实时数据等模型知识之外的网络信息。当用户需要"最新/实时/网上查一下"或问题涉及近期事件、具体网页内容时使用。
type: tool
command: ["python", "scripts/web_search.py"]
timeout: 30
enabled: true
parameters: {"type":"object","properties":{"query":{"type":"string","description":"搜索关键词（中文/英文均可），越具体越好，例如 'GLM-4.5 发布 2025'"},"max_results":{"type":"integer","description":"返回条数，默认 5，最大 10"},"freshness":{"type":"string","description":"时间过滤（可选）：day / week / month / year，仅 Bocha 后端支持"}},"required":["query"]}
---
# web_search（通用联网搜索）

调用搜索 API 返回**结构化结果列表**（title / url / snippet / published），供调用方
Agent 引用、总结、对比或写入笔记。这是 SkillBridge「工具型技能 → Agent」管线的一员，
命令来自受信任的 SKILL.md，Agent 只提供参数（query / max_results / freshness）。

## 后端选择（环境变量，见 backend/.env.example）

- `WEB_SEARCH_PROVIDER=bocha`（默认）：博查 AI 搜索（bochaai.com，国内直连）。
  需在设置界面或 `backend/.env` 配置 `BOCHA_API_KEY`（注册免费获取，有免费额度）。
- `WEB_SEARCH_PROVIDER=wikipedia`：零密钥兜底，走 Wikipedia API，仅覆盖百科类内容。
- 配置了 bocha 但未填 key / 调用失败时，**自动降级到 Wikipedia**，避免静默失败。

## 返回字段

`query` / `provider` / `results`，其中 results 每项为
`{title, url, snippet, published}`（published 可能为空字符串）。

## 说明

- 纯标准库实现（urllib + json），零第三方依赖，契合项目零重依赖约定。
- 本工具只负责**取数**，不负责理解；引用、总结、落库由调用方 Agent 完成。
- 网络不可达时返回 `success: false`，由 Agent 基于自身知识回答并说明原因。
