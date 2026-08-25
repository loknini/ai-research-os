"""工具注册表 + 执行策略（插件化的第一步 + 工具审批 P0）。

设计
----
* 工具 = ``ToolSpec``（name / description / parameters schema / handler / policy）。
  ``@register_tool`` 装饰器把处理函数注册进全局注册表；``backend/server/tools/``
  目录下的模块在 ``discover_tools()`` 时自动导入并自注册——**新增工具无需改动
  Agent 主循环**。
* 技能工具（``skills_bridge`` 的 SKILL.md 目录式发现）与注册表并存：``get_tools()``
  合并两者，``execute()`` 对技能名直接派发到 subprocess。

执行策略（Policy）
------------------
* ``safe``       只读 / 无副作用，直接执行。
* ``sensitive``  写库等有副作用操作：manual / strict 模式下等待用户审批。
* ``dangerous``  删除 / 覆盖等不可逆操作：非 strict 模式一律拒绝（fail-closed）。

审批模式（mode，调用方传入或读环境变量 ``AGENT_APPROVAL_MODE``）
------------------------------------------------------------------
* ``auto``   （默认）sensitive 直接执行；dangerous 拒绝。
* ``manual`` sensitive 等待审批；dangerous 拒绝。
* ``strict`` sensitive 与 dangerous 均等待审批。

审批通道
--------
``execute(..., approve=callable)`` —— ``approve(name, params) -> bool`` 由调用方
决定如何等待用户决策：
* Agent runner 走「DB 落 pending 审批行 + 轮询 + 用户点击」；
* Chat 不传 approve，需要审批的工具在 manual/strict 下自动拒绝（fail-closed），
  auto 模式下行为与以前完全一致。

单工具覆盖：``AGENT_REQUIRE_APPROVAL_TOOLS``（逗号分隔）强制这些工具即使处于
auto 模式也要等待审批（如 ``create_note,create_task``）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# 策略常量
POLICY_SAFE = "safe"
POLICY_SENSITIVE = "sensitive"
POLICY_DANGEROUS = "dangerous"

# 审批模式
MODE_AUTO = "auto"
MODE_MANUAL = "manual"
MODE_STRICT = "strict"


@dataclass
class ToolSpec:
    """一个已注册工具的完整规格。"""

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[[Dict[str, Any], Optional[str]], Dict[str, Any]]
    policy: str = POLICY_SAFE
    source: str = "builtin"


# 全局注册表：tool_name -> ToolSpec
_REGISTRY: Dict[str, ToolSpec] = {}


def register_tool(
    name: Optional[str] = None,
    *,
    description: str = "",
    parameters: Optional[Dict[str, Any]] = None,
    policy: str = POLICY_SAFE,
    source: str = "builtin",
):
    """装饰器：把处理函数注册为工具。

    handler 签名约定：``handler(params: dict, space_id: Optional[str]) -> dict``。
    返回的 dict 会作为 tool 结果 JSON 回灌给模型（须含 ``success`` 等字段）。
    """

    def deco(fn):
        tool_name = name or fn.__name__
        _REGISTRY[tool_name] = ToolSpec(
            name=tool_name,
            description=description,
            parameters=parameters or {"type": "object", "properties": {}},
            handler=fn,
            policy=policy,
            source=source,
        )
        return fn

    return deco


def register_spec(spec: ToolSpec) -> None:
    """直接注册一个 ToolSpec（供程序化注册使用）。"""
    _REGISTRY[spec.name] = spec


def get_spec(name: str) -> Optional[ToolSpec]:
    return _REGISTRY.get(name)


def is_registered(name: str) -> bool:
    return name in _REGISTRY


def list_specs() -> List[ToolSpec]:
    return list(_REGISTRY.values())


def discover_tools() -> int:
    """导入 ``backend/server/tools/`` 下的工具模块（自动自注册）。

    返回注册表里的工具数。幂等：重复调用只触发一次 import（Python 模块缓存）。
    """
    import importlib
    import pkgutil

    from . import tools as tools_pkg

    for mod in pkgutil.iter_modules(tools_pkg.__path__):
        if mod.name.startswith("_"):
            continue
        importlib.import_module(f"{tools_pkg.__name__}.{mod.name}")
    return len(_REGISTRY)


def get_tools() -> List[Dict[str, Any]]:
    """返回 OpenAI function-calling 格式的工具 schema（注册表 + 技能工具）。"""
    from .skills_bridge import get_skill_tools

    tools: List[Dict[str, Any]] = []
    for spec in _REGISTRY.values():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
        )
    tools.extend(get_skill_tools())
    return tools


def is_skill_tool(name: str) -> bool:
    from .skills_bridge import is_skill_tool as _is_skill

    return _is_skill(name)


def tool_needs_approval(
    name: str, mode: Optional[str] = None
) -> Tuple[bool, str]:
    """判断某工具在当前审批模式下是否需要用户审批。

    返回 ``(needed, policy)``；未注册工具 / 技能工具默认不需要审批（技能由
    SKILL.md 白名单兜底，subprocess 无写库副作用）。
    """
    mode = mode or os.environ.get("AGENT_APPROVAL_MODE", MODE_AUTO)
    require_override = {
        t.strip()
        for t in os.environ.get("AGENT_REQUIRE_APPROVAL_TOOLS", "").split(",")
        if t.strip()
    }

    if is_skill_tool(name) or not is_registered(name):
        return False, ""

    spec = get_spec(name)
    if name in require_override:
        return True, spec.policy
    if spec.policy == POLICY_DANGEROUS:
        # 非 strict 下 dangerous 直接拦截（execute 内处理），无需走审批
        return mode == MODE_STRICT, spec.policy
    if spec.policy == POLICY_SENSITIVE:
        return mode != MODE_AUTO, spec.policy
    return False, spec.policy


def execute(
    name: str,
    parameters: Dict[str, Any],
    space_id: Optional[str] = None,
    approve: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """统一工具执行入口（含审批策略）。

    * 技能工具 -> 派发 skills_bridge（subprocess）。
    * 注册表工具 -> 按策略执行；需要审批时通过 ``approve`` 回调征求决策。
    * 未知工具 -> 返回失败结果（不抛异常）。
    """
    from .skills_bridge import invoke_skill

    mode = mode or os.environ.get("AGENT_APPROVAL_MODE", MODE_AUTO)
    require_override = {
        t.strip()
        for t in os.environ.get("AGENT_REQUIRE_APPROVAL_TOOLS", "").split(",")
        if t.strip()
    }

    # —— 技能工具：subprocess 派发（无 DB 写副作用，不参与审批） —— #
    if is_skill_tool(name):
        resolved = space_id if space_id is not None else "__default__"
        return invoke_skill(name, parameters, resolved)

    spec = _REGISTRY.get(name)
    if spec is None:
        return {"success": False, "message": f"未知工具: {name}"}

    # —— 策略判定 —— #
    need_approval = False
    if name in require_override:
        need_approval = True
    elif spec.policy == POLICY_DANGEROUS:
        if mode != MODE_STRICT:
            return {
                "success": False,
                "blocked": True,
                "message": (
                    f"工具 {name} 已被策略拦截（dangerous 不可逆操作，"
                    f"当前审批模式 {mode}，可用 AGENT_APPROVAL_MODE=strict 改为等待审批）"
                ),
            }
        need_approval = True
    elif spec.policy == POLICY_SENSITIVE:
        need_approval = mode != MODE_AUTO

    if need_approval:
        if approve is None:
            return {
                "success": False,
                "blocked": True,
                "message": (
                    f"工具 {name} 需要审批，但当前调用方未提供审批通道"
                    f"（审批模式 {mode}）；该调用已被拒绝"
                ),
            }
        ok = approve(name, parameters)
        if not ok:
            return {
                "success": False,
                "blocked": True,
                "denied": True,
                "message": f"用户拒绝了工具 {name} 的调用",
            }

    # —— 执行 —— #
    try:
        return spec.handler(parameters, space_id=space_id)
    except Exception as exc:  # noqa: BLE001 - 工具失败必须以结果返回，不能抛给主循环
        return {"success": False, "message": f"执行失败: {str(exc)}"}


# 模块导入时立即发现内置工具（幂等；独立 CLI 回退路径下 tools 包不可导入会静默跳过）
try:  # pragma: no cover - 后端环境必走；独立 CLI 兜底
    discover_tools()
except Exception:  # pragma: no cover - 独立 CLI（scripts 目录直跑）时 backend 包可能不可用
    pass


__all__ = [
    "ToolSpec",
    "POLICY_SAFE",
    "POLICY_SENSITIVE",
    "POLICY_DANGEROUS",
    "MODE_AUTO",
    "MODE_MANUAL",
    "MODE_STRICT",
    "register_tool",
    "register_spec",
    "get_spec",
    "is_registered",
    "list_specs",
    "discover_tools",
    "get_tools",
    "is_skill_tool",
    "tool_needs_approval",
    "execute",
]
