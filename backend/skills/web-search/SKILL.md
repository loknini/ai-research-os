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

## 何时调用 / 何时不调用

- 调用：用户问 cutoff 之后的事（发布、新闻、价格、版本）；答案需要来源链接或可验证的外部事实；问题涉及近期事件、具体网页内容。
- 不调用：自身知识可可靠回答且不受时间影响的问题；图片分析（那是公式/视觉类工具的事）。

## 后端选择（环境变量，见 backend/.env.example）

- `WEB_SEARCH_PROVIDER` 显式指定则优先；默认链：`duckduckgo`（零密钥开箱）→ `bocha`（需 `BOCHA_API_KEY`，质量更高）→ `wikipedia`（零密钥兜底，仅百科）。
- `BOCHA_API_KEY` 支持逗号分隔多 key；401/403/429 时自动轮换下一个 key 再换引擎（key 本身永不回传）。
- 任一源失败自动降级，不静默失败。

## 返回字段

成功：`{success, provider, engine, status:"ok", query, results, uncertainty[], warnings[], attempts[]}`；
失败：`{success:false, status:"unavailable", error, attempts[]}`（旧 `provider/query/results` 字段保留兼容）。
其中 results 每项为 `{title, url, snippet, published}`（published 可能为空字符串）；
`attempts` 逐条记录 `{provider, ok, error?, durationSeconds, keyIndex?}`。

## 回传规则（调用方必须遵守）

- `uncertainty` 是对**事实**的怀疑（缺口、冲突、过期）：写进答案当 caveat。
- `warnings` 是对**路由**的说明（降级、轮换、忽略的参数）：决定采信程度，不当事实引用。
- 引用必须带 `results[].url` 来源链接；`status` 非 `ok` 时如实说明覆盖缺口。

## 说明

- 纯标准库实现（urllib + json + re + socket + time），零第三方依赖，契合项目零重依赖约定。
- 本工具只负责**取数**，不负责理解；引用、总结、落库由调用方 Agent 完成。
- 网络不可达时返回 `success: false`（附 `attempts` 诊断），由 Agent 基于自身知识回答并说明原因。
