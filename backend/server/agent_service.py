#!/usr/bin/env python3
"""
Multi-Agent Service - 可配置角色管线（Phase 3）

职责：把一个需求依次交给若干「角色（role）」处理，每个角色的输出作为下一个角色的输入。

* 角色管线由 ``backend/agent_roles.json`` 配置驱动（顺序 = 管线顺序，``enabled`` 控制是否启用）。
  不修改代码即可增删角色、调整顺序、开关某一角色。
* 内置角色：``architect``（架构师）、``planner``（规划师）、``developer``（开发者）、
  ``reviewer``（评审者）。前端 ``agent-workflow.tsx`` 的 developer/reviewer 占位由此真正生效。
* 每个角色 = 一段 system prompt + 一个可选的「结构化解析器」（把 LLM 文本抽成 JSON/字典）。
* ``run_full_workflow(requirement, role_keys=None)`` 顺序执行；``role_keys`` 可在请求里指定
  本次要跑哪些角色（覆盖配置），便于按需裁剪。

LLM 调用仍委派给可配置的 ``llm.py`` 客户端（见 ``call_llm``），不可达时抛
``LLMUnavailableError``，由上层 SSE 路由转为 error 事件。
"""
import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional, Generator

from jsonschema import ValidationError, validate as validate_json

if __name__ == "__main__" and not __package__:
    print(
        "Run this package CLI with: python -m backend.server.agent_service <command> [args]",
        file=sys.stderr,
    )
    raise SystemExit(2)

# 后端 LLM 客户端（可选导入）
try:
    from backend.server.llm import llm_client, LLMUnavailableError
except Exception:
    llm_client = None

    class LLMUnavailableError(Exception):
        pass

# 共享上下文管理（token 估算 / 历史摘要 / 消息压缩）
from .context import compact_messages

# 工具审批策略（工具注册表提供）
try:
    from .tool_registry import tool_needs_approval
except Exception:  # pragma: no cover - 独立 CLI 回退
    def tool_needs_approval(name, mode=None):
        return False, ""


def call_llm(messages: List[Dict[str, str]], temperature: float = 0.7,
             model: Optional[str] = None, max_tokens: Optional[int] = None) -> str:
    """调用 LLM；优先走可配置的 llm.py，失败回退到本地 urllib 实现。"""
    if llm_client is not None:
        try:
            text = llm_client.call_llm(
                messages, temperature=temperature, model=model, max_tokens=max_tokens)
            if text is None:
                raise LLMUnavailableError("LLM 返回空响应（服务不可用）")
            return text
        except LLMUnavailableError:
            raise
    return _legacy_call_llm(messages, temperature)


def _legacy_call_llm(messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
    """旧的 LLM urllib 实现（独立 CLI 运行时使用）。"""
    try:
        url = f"{os.environ.get('LLM_BASE_URL', 'http://localhost:11434/v1')}/chat/completions"
        data = {
            "model": os.environ.get('LLM_MODEL', 'deepseek-chat'),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4000,
            "stream": False,
        }
        req = urllib.request.Request(
            url, data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}, method='POST'
        )
        if os.environ.get('LLM_API_KEY'):
            req.add_header('Authorization', f'Bearer {os.environ["LLM_API_KEY"]}')
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.loads(response.read().decode('utf-8'))['choices'][0]['message']['content']
    except Exception as e:
        return f"Error: {str(e)}"


# --------------------------------------------------------------------------- #
# 内置角色（system prompt + 可选解析器）
# --------------------------------------------------------------------------- #
class ArchitectAgent:
    SYSTEM_PROMPT = """你是一位经验丰富的软件架构师。你的任务是根据用户需求，设计完整的技术方案。

你可以调用工具获取真实信息：需要最新技术资讯、框架选型对比、市场/生态信息时，先用 `web_search` 联网搜索（参数：query 关键词）；检索论文用 `arxiv_reader`。工具结果会自动回灌给你，请基于真实信息作答，不要编造数据、版本号或链接。

请按照以下结构输出你的设计：

## 1. 项目概述
简要描述项目的目标和核心价值

## 2. 技术栈推荐
列出推荐的前端、后端、数据库、部署等技术，并说明选择理由

## 3. 项目目录结构
使用树形结构展示推荐的目录组织

## 4. 核心模块设计
描述主要的模块划分和职责

## 5. API 设计 (如适用)
列出核心 API 端点

## 6. 数据模型 (如适用)
描述核心数据结构

请用中文回答，保持专业、清晰、可执行。"""

    def _parse_design(self, text: str) -> Dict[str, Any]:
        import re
        result = {"overview": "", "tech_stack": [], "directory_structure": [], "modules": [], "apis": [], "data_models": []}
        overview_match = re.search(r'## 1\. 项目概述\s*\n(.*?)(?=##|\Z)', text, re.DOTALL)
        if overview_match:
            result["overview"] = overview_match.group(1).strip()
        tech_match = re.search(r'## 2\. 技术栈推荐\s*\n(.*?)(?=##|\Z)', text, re.DOTALL)
        if tech_match:
            items = re.findall(r'[-*]\s*(.+?)(?=\n[-*]|\n##|\Z)', tech_match.group(1), re.DOTALL)
            result["tech_stack"] = [i.strip().replace('\n', ' ') for i in items]
        dir_match = re.search(r'## 3\. 项目目录结构\s*\n(```[\s\S]*?```|.*?)(?=##|\Z)', text, re.DOTALL)
        if dir_match:
            result["directory_structure"] = [l.strip() for l in dir_match.group(1).replace('```', '').strip().split('\n') if l.strip()]
        module_match = re.search(r'## 4\. 核心模块设计\s*\n(.*?)(?=##|\Z)', text, re.DOTALL)
        if module_match:
            modules = re.findall(r'###?\s*(.+?)\s*\n(.*?)(?=###?\s|\Z)', module_match.group(1), re.DOTALL)
            result["modules"] = [{"name": m[0].strip(), "description": m[1].strip()} for m in modules]
        api_match = re.search(r'## 5\. API 设计.*?\n(.*?)(?=##|\Z)', text, re.DOTALL)
        if api_match:
            apis = re.findall(r'[-*]\s*`?(GET|POST|PUT|DELETE)\s+(/[^`\s]+)`?\s*[:-]?\s*(.+?)(?=\n[-*]|\n##|\Z)', api_match.group(1), re.DOTALL)
            result["apis"] = [{"method": a[0], "path": a[1], "description": a[2].strip()} for a in apis]
        return result


class PlannerAgent:
    SYSTEM_PROMPT = """你是一位专业的项目管理专家。你的任务是根据技术方案，制定详细的开发计划。

你可以调用工具获取真实信息：需要了解团队规模、行业惯例、技术风险等外部信息时，先用 `web_search` 联网搜索（参数：query 关键词）。工具结果会自动回灌给你，请基于真实信息作答。

请按照以下结构输出你的规划：

## 1. 开发阶段划分
将项目划分为几个主要阶段

## 2. 详细任务列表
为每个阶段列出具体任务，每个任务包含：
- 任务名称
- 任务描述
- 依赖任务（如果有）
- 预估工时
- 优先级 (high/medium/low)

## 3. 关键路径
指出哪些任务是项目的关键路径

## 4. 里程碑
定义项目的主要里程碑节点

## 5. 风险提醒
指出可能的风险点和注意事项

请用 JSON 格式输出任务列表，便于程序解析。格式如下：
```json
{
  "phases": [
    {
      "name": "阶段名称",
      "tasks": [
        {"id": "task_1", "name": "任务名称", "description": "任务描述", "dependencies": [], "estimated_hours": 4, "priority": "high"}
      ]
    }
  ],
  "milestones": [{"name": "里程碑名称", "description": "完成标准"}],
  "risks": ["风险1", "风险2"]
}
```

请用中文回答。"""

    def _parse_plan(self, text: str) -> Dict[str, Any]:
        import re
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        json_match = re.search(r'\{\s*"phases"[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        return {"phases": [], "milestones": [], "risks": []}


class DeveloperAgent:
    SYSTEM_PROMPT = """你是一位资深软件工程师。根据上游提供的技术方案与开发计划，产出可落地的实现指南。

你可以调用工具获取真实信息：需要确认 API 用法、框架文档、版本信息时，先用 `web_search` 联网搜索（参数：query 关键词）。工具结果会自动回灌给你，请基于真实信息作答，不要编造 API 或版本号。

请聚焦「怎么写代码」，按以下结构输出：
## 1. 需要创建/修改的文件清单
## 2. 关键模块与函数签名
## 3. 核心算法 / 关键逻辑伪代码
## 4. 边界条件与异常处理
## 5. 与上下游模块的衔接点

用中文，结构清晰，避免空泛描述。"""


class ReviewerAgent:
    SYSTEM_PROMPT = """你是一位严谨的技术评审专家。根据上游产物（方案 / 计划 / 实现指南），进行评审。

你可以调用工具核实信息：对上游引用的技术选型、版本号、数据有疑问时，用 `web_search` 联网搜索核验（参数：query 关键词），基于真实信息给出评审结论。

请按以下结构输出：
## 1. 严重问题（必须修复）
## 2. 设计缺陷 / 遗漏
## 3. 可维护性与安全问题
## 4. 改进建议
## 5. 总体结论（可否进入下一阶段）

用中文要点输出，按严重程度排序；若无问题也请明确说明。"""


# 结构化解析器注册表（角色可选引用）
def _parse_design(text):
    return ArchitectAgent()._parse_design(text)


def _parse_plan(text):
    return PlannerAgent()._parse_plan(text)


PARSERS = {"design": _parse_design, "plan": _parse_plan}

# 内置角色定义（system prompt 与解析器）。配置文件可覆盖 enabled，也可覆盖 system。
BUILTIN_ROLES: Dict[str, Dict[str, Any]] = {
    "architect": {"label": "架构师", "system": ArchitectAgent.SYSTEM_PROMPT, "parser": "design"},
    "planner":   {"label": "规划师", "system": PlannerAgent.SYSTEM_PROMPT,   "parser": "plan"},
    "developer": {"label": "开发者", "system": DeveloperAgent.SYSTEM_PROMPT, "parser": None},
    "reviewer":  {"label": "评审者", "system": ReviewerAgent.SYSTEM_PROMPT,  "parser": None},
}

# 配置文件路径：backend/agent_roles.json
_ROLES_CONFIG = Path(__file__).resolve().parent.parent / "agent_roles.json"

# 缺省管线（配置文件不存在时使用）：架构 -> 规划 -> 评审
_DEFAULT_PIPELINE = ["architect", "planner", "reviewer"]


def load_role_config() -> List[str]:
    """读取 agent_roles.json，返回「启用且内置存在」的角色 key 列表（保持文件顺序）。"""
    if not _ROLES_CONFIG.exists():
        return list(_DEFAULT_PIPELINE)
    try:
        data = json.loads(_ROLES_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return list(_DEFAULT_PIPELINE)
    roles = data.get("roles", [])
    keys = [r["key"] for r in roles if r.get("enabled", True) and r.get("key") in BUILTIN_ROLES]
    return keys or list(_DEFAULT_PIPELINE)


def resolve_role(key: str) -> Dict[str, Any]:
    """把角色 key 解析成运行期 spec（合并内置默认与配置覆盖）。"""
    spec = dict(BUILTIN_ROLES[key])
    if _ROLES_CONFIG.exists():
        try:
            data = json.loads(_ROLES_CONFIG.read_text(encoding="utf-8"))
            for r in data.get("roles", []):
                if r.get("key") == key:
                    if r.get("system"):
                        spec["system"] = r["system"]
                    if "parser" in r:
                        spec["parser"] = r["parser"]
                    if r.get("label"):
                        spec["label"] = r["label"]
        except Exception:
            pass
    return spec


# --------------------------------------------------------------------------- #
# 通用角色执行器
# --------------------------------------------------------------------------- #
def _safe_params(arguments) -> dict:
    """将工具参数归一化为 dict（兼容已解析对象与增量 JSON 字符串）。"""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        if not arguments.strip():
            return {}
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return {}
    return arguments if isinstance(arguments, dict) else {}


def _load_agent_tools():
    """懒加载 Chat Agent 的工具清单与执行器（复用同一套 TOOLS / execute_tool）。

    返回 (tools, execute_tool)；独立 CLI 运行（后端不可达）时退化为 (None, None)，
    角色退化为纯文本调用，保持向后兼容。
    """
    try:
        from scripts.chat_agent_stream import TOOLS, execute_tool
        return (TOOLS or None), execute_tool
    except Exception:
        return None, None


def run_role(
    key: str,
    input_text: str,
    space_id: str | None = None,
    enable_tools: bool = True,
    node_spec: Optional[Dict[str, Any]] = None,
    approval_mode: Optional[str] = None,
) -> Generator[Dict[str, Any], None, None]:
    """执行单个角色，产出 start / progress / complete 事件流。

    启用工具时走「ReAct 循环」：携带与 Chat Agent 相同的 TOOLS 列表，模型可
    调用 ``web_search`` / ``arxiv_reader`` 等技能，结果回灌后继续推理，直到
    产出最终回答或达到最大轮次（防止无限循环）。``space_id`` 沿调用链透传给
    工具执行器，保证写入型工具按空间隔离落库。

    新增三块能力（对齐 DeepSeek Harness 的工程纪律）：
    1. **工具审批**：敏感/危险工具在需要审批时 yield 内部事件
       ``{"type": "__approval_required", ...}`` 并**暂停**，等待消费方
       ``gen.send(decision)`` 回传 True/False 后继续（拒绝即 fail-closed）。
    2. **可重放日志**：每轮模型实际看到的消息序列 yield 内部事件
       ``{"type": "__replay", "phase": key, "round": n, "messages": [...]}``，
       由 runner 落库到 ``agent_replay_messages``。
    3. **上下文管理**：消息超预算时用 LLM 把早期历史压缩成摘要（见
       ``context.compact_messages``），替代粗暴的轮次截断。
    """
    if node_spec is None:
        spec = resolve_role(key)
    else:
        spec = {
            "label": node_spec.get("name", key),
            "system": node_spec.get("systemPrompt", ""),
            "parser": None,
            **node_spec,
        }
    label = spec["label"]
    model = spec.get("model") or None
    temperature = spec.get("temperature")
    max_tokens = spec.get("maxTokens")

    yield {"type": "start", "agent": key, "message": f"开始{label}..."}

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": spec["system"]},
        {"role": "user", "content": input_text},
    ]
    # 初始消息即落重放（round 0），保证"模型看到的一切都能重建"。
    yield {"type": "__replay", "phase": key, "round": 0, "messages": list(messages)}

    # 懒加载工具（仅在 LLM 客户端可用时启用 function calling）
    tools = None
    execute_tool = None
    if enable_tools and llm_client is not None:
        tools, execute_tool = _load_agent_tools()
        if node_spec is not None:
            allowed = set(node_spec.get("allowedTools") or [])
            tools = [tool for tool in (tools or [])
                     if tool.get("function", {}).get("name") in allowed] or None

    # 安全上限 + 上下文预算（环境变量可调；压缩替代粗暴截断）
    MAX_TOOL_ROUNDS = int(os.environ.get("AGENT_MAX_TOOL_ROUNDS", "8"))
    CONTEXT_LIMIT = int(os.environ.get("AGENT_CONTEXT_TOKEN_LIMIT", "24000"))
    CONTEXT_KEEP_LAST = int(os.environ.get("AGENT_CONTEXT_KEEP_LAST", "6"))

    final_text = ""
    try:
        for _round in range(1, MAX_TOOL_ROUNDS + 1):
            # —— 上下文管理：超预算则把早期历史压缩为摘要（不破坏 tool 配对） ——
            messages, compressed = compact_messages(
                messages, limit=CONTEXT_LIMIT, keep_last=CONTEXT_KEEP_LAST)
            if compressed:
                yield {
                    "type": "context_compressed",
                    "agent": key,
                    "round": _round,
                    "message": "上下文已自动压缩：早期历史已摘要化，最近的对话完整保留",
                }

            if tools is not None:
                # —— 工具路径：流式 + 原生 function calling —— #
                assistant_text = ""
                tool_calls_this_round: List[dict] = []
                for item in llm_client.stream_llm(
                    messages, tools=tools, model=model,
                    temperature=temperature, max_tokens=max_tokens):
                    if isinstance(item, str):
                        assistant_text += item
                    elif isinstance(item, dict) and "tool_calls" in item:
                        tool_calls_this_round = item["tool_calls"]
            else:
                # —— 无工具路径：纯文本调用（兼容独立 CLI / 旧行为） —— #
                assistant_text = call_llm(
                    messages, temperature=temperature if temperature is not None else 0.7,
                    model=model, max_tokens=max_tokens) or ""
                tool_calls_this_round = []

            final_text = assistant_text
            if not tool_calls_this_round:
                break  # 本轮没有请求工具 -> 已是最终回答

            # 执行本轮的工具调用并回灌，进入下一轮反思
            results = []
            for call in tool_calls_this_round:
                name = call.get("name") or ""
                params = _safe_params(call.get("arguments"))

                # —— 工具审批：敏感/危险工具需要审批时暂停，等待消费方决策 ——
                need_approval, policy = tool_needs_approval(name, mode=approval_mode)
                decision: Optional[bool] = None
                if need_approval:
                    approval_id = str(uuid.uuid4())
                    decision = yield {
                        "type": "__approval_required",
                        "tool": name,
                        "params": params,
                        "approvalId": approval_id,
                        "policy": policy,
                    }
                    if decision is None:
                        decision = False  # 无决策者（legacy 消费方）-> 拒绝（fail-closed）

                yield {
                    "type": "progress",
                    "agent": key,
                    "step": f"正在调用 {name} 获取信息…"
                    + ("" if decision is None else ("（已获审批）" if decision else "（已被拒绝）")),
                }
                try:
                    result = execute_tool(
                        name, params, space_id=space_id,
                        approve=(lambda n, p: bool(decision)) if decision is not None else None,
                        mode=approval_mode,
                    )
                except Exception as exc:  # 防御性兜底
                    result = {"success": False, "error": f"工具执行异常: {exc}"}
                yield {
                    "type": "progress",
                    "agent": key,
                    "step": f"{name} 已返回结果",
                }
                results.append((call.get("id", ""), name, result, params))

            messages.append({
                "role": "assistant",
                "content": assistant_text,
                "tool_calls": [
                    {
                        "id": cid,
                        "type": "function",
                        "function": {
                            "name": cname,
                            "arguments": json.dumps(args, ensure_ascii=False),
                        },
                    }
                    for (cid, cname, _res, args) in results
                ],
            })
            for cid, cname, res, _args in results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": cid,
                    "content": json.dumps(res, ensure_ascii=False),
                })

            # 本轮完整消息序列落重放（模型下一轮实际看到的内容）
            yield {"type": "__replay", "phase": key, "round": _round, "messages": list(messages)}
        else:
            # 达到最大轮次仍有未处理的工具调用：强制做一次无工具的最终回答
            final_text = call_llm(
                messages, temperature=temperature if temperature is not None else 0.7,
                model=model, max_tokens=max_tokens) or ""
    except LLMUnavailableError as exc:
        yield {"type": "error", "message": f"{label}调用 LLM 失败：{exc}"}
        return

    if not final_text or not final_text.strip():
        yield {"type": "error", "message": f"{label}未返回有效内容"}
        return

    parser = spec.get("parser")
    structured = PARSERS[parser](final_text) if parser else None
    output_contract = spec.get("output") or {"type": "text"}
    if output_contract.get("type") == "json_schema":
        schema = output_contract.get("schema") or {}
        try:
            structured = _parse_json_output(final_text)
            validate_json(instance=structured, schema=schema)
        except (json.JSONDecodeError, ValidationError, ValueError) as first_error:
            repair_messages = [
                {"role": "system", "content": "Repair the response. Output only valid JSON matching the supplied JSON Schema."},
                {"role": "user", "content": json.dumps({
                    "schema": schema, "invalidResponse": final_text,
                    "validationError": str(first_error),
                }, ensure_ascii=False)},
            ]
            repaired = call_llm(repair_messages, temperature=0, model=model, max_tokens=max_tokens) or ""
            try:
                structured = _parse_json_output(repaired)
                validate_json(instance=structured, schema=schema)
                final_text = repaired
            except (json.JSONDecodeError, ValidationError, ValueError) as repair_error:
                yield {"type": "error", "agent": key,
                       "message": f"{label} structured output validation failed after one repair: {repair_error}"}
                return

    yield {
        "type": "complete",
        "agent": key,
        "result": {"success": True, "raw_output": final_text, "structured": structured},
    }


def _parse_json_output(text: str) -> Any:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return json.loads(value)


def run_node(node_spec: Dict[str, Any], input_text: str,
             space_id: str | None = None,
             approval_mode: str = "manual") -> Generator[Dict[str, Any], None, None]:
    """Execute a snapshotted DAG node; ``run_role`` remains the legacy wrapper."""
    node_id = str(node_spec.get("id") or "node")
    return run_role(node_id, input_text, space_id=space_id,
                    enable_tools=True, node_spec=node_spec, approval_mode=approval_mode)


# 内部事件前缀：仅供 runner 消费（审批/重放），对外消费方一律过滤。
_INTERNAL_EVENT_PREFIX = "__"


def _is_internal_event(ev: Dict[str, Any]) -> bool:
    return str(ev.get("type", "")).startswith(_INTERNAL_EVENT_PREFIX)


def run_full_workflow(
    requirement: str,
    role_keys: Optional[List[str]] = None,
    space_id: str | None = None,
) -> Generator[Dict[str, Any], None, None]:
    """按顺序执行角色管线，上游 raw_output 作为下游输入。

    内部事件（``__approval_required`` / ``__replay``）在此过滤，不对外暴露；
    遇到需要审批的工具时按「拒绝」处理（fail-closed）。
    """
    if role_keys:
        keys = [k for k in role_keys if k in BUILTIN_ROLES]
    else:
        keys = load_role_config()

    if not keys:
        yield {"type": "error", "message": "没有启用的角色"}
        return

    current_input = requirement
    for idx, key in enumerate(keys):
        spec = resolve_role(key)
        yield {
            "type": "phase_start",
            "phase": key,
            "label": spec["label"],
            "message": f"=== Phase {idx + 1}: {spec['label']} ===",
        }

        last = None
        for ev in run_role(key, current_input, space_id=space_id):
            if _is_internal_event(ev):
                continue
            yield ev
            if ev["type"] == "complete":
                last = ev

        if last is None or not last.get("result", {}).get("success"):
            yield {"type": "error", "message": f"{spec['label']}执行失败"}
            return

        current_input = last["result"]["raw_output"]

    yield {"type": "workflow_complete", "message": "多 Agent 协作完成！"}


# --------------------------------------------------------------------------- #
# 向后兼容的薄封装（保留原函数名，供 CLI / 旧调用方使用）
# --------------------------------------------------------------------------- #
def run_architect_agent(requirement: str) -> Generator[Dict[str, Any], None, None]:
    for ev in run_role("architect", requirement):
        if not _is_internal_event(ev):
            yield ev


def run_planner_agent(design_output: str) -> Generator[Dict[str, Any], None, None]:
    for ev in run_role("planner", design_output):
        if not _is_internal_event(ev):
            yield ev


# CLI 测试
if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m backend.server.agent_service <command> [args]", file=sys.stderr)
        print("Commands: architect, planner, workflow, roles", file=sys.stderr)
        sys.exit(1)
    command = sys.argv[1]
    if command == "roles":
        print(json.dumps(load_role_config(), ensure_ascii=False))
    elif command == "architect":
        req = sys.argv[2] if len(sys.argv) > 2 else "创建一个待办事项管理应用"
        for u in run_architect_agent(req):
            print(json.dumps(u, ensure_ascii=False))
    elif command == "planner":
        d = sys.argv[2] if len(sys.argv) > 2 else "待办事项应用，使用 React + TypeScript"
        for u in run_planner_agent(d):
            print(json.dumps(u, ensure_ascii=False))
    elif command == "workflow":
        req = sys.argv[2] if len(sys.argv) > 2 else "创建一个待办事项管理应用"
        for u in run_full_workflow(req):
            print(json.dumps(u, ensure_ascii=False))
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
