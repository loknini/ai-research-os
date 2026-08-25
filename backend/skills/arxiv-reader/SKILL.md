---
name: arxiv_reader
description: 从 arXiv 抓取论文（给定 arxiv_id/URL 或关键词），返回结构化元数据（标题、作者、摘要、PDF 链接、分类、发表日期）。用于论文检索与精读前的素材获取；深度阅读与总结由调用方 Agent 基于返回内容完成。
type: tool
command: ["python", "scripts/fetch_arxiv.py"]
timeout: 60
enabled: true
parameters: {"type":"object","properties":{"arxiv_id":{"type":"string","description":"arXiv ID 或 URL，如 1706.03762 或 https://arxiv.org/abs/1706.03762；指定时优先于 query"},"query":{"type":"string","description":"搜索关键词或标题片段，如 'attention is all you need'"},"max_results":{"type":"integer","description":"搜索返回条数","default":3}},"required":[]}
---
# arxiv_reader（arXiv 论文抓取）

本工具型技能从 arXiv 官方 API 抓取论文，并返回**结构化 JSON**，供调用方 Agent 进一步
阅读、总结或落库。这是「生态技能 → Agent」管线的范例：命令来自受信任的 SKILL.md，
Agent 只提供参数（arxiv_id / query / max_results）。

## 使用约定

- 指定 `arxiv_id` 时按单篇精确抓取；否则用 `query` 做关键词搜索（默认返回 3 篇）。
- 返回字段：`arxiv_id` / `title` / `authors` / `summary`（摘要）/ `pdf_url` /
  `url` / `primary_category` / `categories` / `published` / `comment` / `doi`。
- 本工具只负责**取数**，不负责理解；深度阅读请基于 `summary` 或下载 `pdf_url` 后由
  Agent 的 LLM 完成（与生态 `arxiv-reader` 的「LLM Agent 精读」意图一致，但更轻、更稳）。

## 说明

- 纯标准库实现（urllib + xml.etree），零第三方依赖，契合本项目的零依赖约定。
- 若要替换为功能更完整的生态版 `arxiv-reader`（基于 LLM 的分类与精读），在部署环境
  安装其 `requirements.txt`、配置 LLM 环境变量后，把本 SKILL.md 的 `command` 指向
  其 `main.py` 即可，桥接层与 Agent 调用方式无需改动。
