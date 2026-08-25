"""SkillBridge — 让后端 ChatAgent / 多 Agent 工作流能"调用"技能（skill）的通用适配层。

设计目标
--------
对齐市场主流 coding agent（Claude Code / OpenAI Codex / opencode）遵循的
**Agent Skills 开放标准**：技能以 ``skills/<name>/SKILL.md`` 目录形式存放，
``SKILL.md`` 用 frontmatter（name / description）+ markdown 正文描述"怎么做"。

本桥同时支持两类技能（对应市场上"两层模型"的两层）：

1. **指令型（instruction，默认）** —— 只有 ``SKILL.md`` 正文，没有可执行入口。
   被 Agent 调用时，把正文作为工作指引回灌给模型，模型照着用**既有工具**
   （fetch_papers / create_task / …）去执行。这是 Claude Code / Codex 的默认形态。
2. **工具型（tool）** —— 带有 ``scripts/`` 可执行脚本（或 SKILL.md 里声明 ``command``）。
   被 Agent 调用时，通过 subprocess 执行：参数以 JSON 写入子进程 **stdin**，
   环境变量 ``X_SPACE_KEY=space_id`` 让脚本遵守空间隔离，stdout 解析为 JSON 回灌模型。

安全与白名单
------------
* ``backend/skills/`` 目录下的发现结果即**白名单**：只有存在 ``SKILL.md`` 且
  ``enabled: true`` 的技能才能被调用；命令来自受信任的 SKILL.md 文件，
  **模型只提供参数，永远不能指定要执行什么命令**。
* 永不抛异常：任何失败都返回 ``{"success": False, "error": ...}``。
* 渐进式披露：目录式发现让技能文件可直接复用 Claude/Codex 生态里现成的
  ``SKILL.md``（跨工具可移植），而无需自造注册表格式。

加一个技能 = 在 ``backend/skills/<name>/`` 放一个 ``SKILL.md``（+ 可选 ``scripts/``），
无需改动 Agent 循环代码。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 技能目录：backend/skills/<name>/SKILL.md（相对本文件的父目录的父目录）
SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

# 模块加载时一次性发现（技能目录是静态配置，运行期不变；可用 reload_skills() 刷新）
_REGISTRY: Dict[str, Dict[str, Any]] = {}


# --------------------------------------------------------------------------- #
# SKILL.md 解析（零依赖的极简 frontmatter 解析器）
# --------------------------------------------------------------------------- #
def _parse_frontmatter(text: str) -> (Dict[str, Any], str):
    """解析 ``SKILL.md`` 的 YAML frontmatter（极简子集）与正文。

    仅支持本项目需要的字段：标量（name/description/type/enabled/timeout/command）
    以及单行 JSON 块（parameters）。足以覆盖 Agent Skills 标准的核心约定，
    且无需引入 PyYAML 等第三方依赖。
    """
    if not text.lstrip().startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text

    fm_lines = lines[1:end]
    body = "\n".join(lines[end + 1:]).strip()
    meta: Dict[str, Any] = {}

    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        # 单行 JSON 块（parameters 等）：先试单行解析，失败再向下累积到可解析为止
        if val[:1] in ("{", "["):
            try:
                meta[key] = json.loads(val)
                i += 1
                continue
            except json.JSONDecodeError:
                pass
            buf = val
            j = i + 1
            while j < len(fm_lines):
                buf += "\n" + fm_lines[j]
                try:
                    meta[key] = json.loads(buf)
                    i = j + 1
                    break
                except json.JSONDecodeError:
                    j += 1
            else:
                meta[key] = val  # 解析失败则保留原串
                i = j
            continue
        # 标量
        low = val.lower()
        if low in ("true", "false"):
            meta[key] = low == "true"
        elif low.isdigit():
            meta[key] = int(val)
        else:
            meta[key] = val
        i += 1

    return meta, body


def _as_cmd_list(cmd: Any) -> List[str]:
    """把 command 字段规范成参数列表。"""
    if isinstance(cmd, list):
        return list(cmd)
    if isinstance(cmd, str):
        return cmd.split()
    return []


def _resolve_command(command: List[str]) -> List[str]:
    """把命令首项的 'python'/'python3' 替换为当前解释器，保证用对环境。"""
    cmd = list(command)
    if cmd and cmd[0] in ("python", "python3"):
        cmd[0] = sys.executable
    return cmd


# --------------------------------------------------------------------------- #
# 目录发现
# --------------------------------------------------------------------------- #
def _discover() -> Dict[str, Dict[str, Any]]:
    """扫描 ``backend/skills/<name>/SKILL.md``，返回 {tool_name: spec}（仅含 enabled）。"""
    specs: Dict[str, Dict[str, Any]] = {}
    if not SKILLS_DIR.exists():
        return specs
    for d in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            meta, body = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        except Exception:
            continue

        name = meta.get("name") or d.name
        if not meta.get("enabled", True):
            continue

        stype = meta.get("type", "instruction")
        spec: Dict[str, Any] = {
            "name": name,
            "description": meta.get("description", ""),
            "type": stype,
            "body": body,
            "dir": str(d),
            "path": str(skill_md),
            "enabled": bool(meta.get("enabled", True)),
        }

        if stype == "tool":
            cmd = meta.get("command")
            if not cmd:
                # 默认约定：scripts/<dir-name>.py
                default = d / "scripts" / f"{d.name}.py"
                cmd = [str(default)] if default.exists() else None
            if not cmd:
                # 没有可执行入口的工具型技能退化为指令型，避免注册一个调不动的死工具
                spec["type"] = "instruction"
            else:
                spec["command"] = _as_cmd_list(cmd)
                spec["timeout"] = int(meta.get("timeout", 60))
                spec["parameters"] = meta.get("parameters") or {
                    "type": "object",
                    "properties": {
                        "input": {"type": "string", "description": "传给技能的原始输入"}
                    },
                    "required": [],
                }

        specs[name] = spec
    return specs


_REGISTRY = _discover()


def reload_skills() -> int:
    """重新扫描技能目录（运行期新增/修改技能后调用）。返回发现的技能数量。"""
    global _REGISTRY
    _REGISTRY = _discover()
    return len(_REGISTRY)


def scan_skills() -> List[Dict[str, Any]]:
    """扫描全部技能目录（含 disabled），供管理界面展示。

    返回列表中每个技能都带 ``enabled`` 与 ``path`` 字段；工具型技能额外带
    ``hasScript`` 指示是否真有可执行入口。
    """
    result: List[Dict[str, Any]] = []
    if not SKILLS_DIR.exists():
        return result
    for d in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            meta, _body = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        except Exception:
            continue
        name = meta.get("name") or d.name
        stype = meta.get("type", "instruction")
        has_script = False
        if stype == "tool":
            cmd = meta.get("command")
            if cmd:
                has_script = True
            else:
                default = d / "scripts" / f"{d.name}.py"
                has_script = default.exists()
        result.append(
            {
                "name": name,
                "type": stype,
                "description": meta.get("description", ""),
                "enabled": bool(meta.get("enabled", True)),
                "hasScript": has_script,
                "path": str(skill_md),
            }
        )
    return result


def set_skill_enabled(name: str, enabled: bool) -> bool:
    """修改某技能的启用状态（改写其 SKILL.md frontmatter 的 ``enabled`` 行）。

    成功改写并刷新运行期注册表后返回 ``True``；找不到该技能返回 ``False``。
    """
    for s in scan_skills():
        if s["name"] != name:
            continue
        p = Path(s["path"])
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            return False
        new_val = "true" if enabled else "false"
        pat = re.compile(r"^(enabled\s*:\s*)(true|false)\s*$", re.MULTILINE)
        if pat.search(text):
            text = pat.sub(lambda m: f"{m.group(1)}{new_val}", text)
        else:
            # frontmatter 内没有 enabled 行：在开头的 --- 之后插入一行
            text = text.replace("---", f"---\nenabled: {new_val}", 1)
        try:
            p.write_text(text, encoding="utf-8")
        except Exception:
            return False
        reload_skills()
        return True
    return False


# --------------------------------------------------------------------------- #
# 对外 API
# --------------------------------------------------------------------------- #
def get_skill_tools() -> List[Dict[str, Any]]:
    """返回所有已启用技能的 OpenAI function-calling 工具 schema。

    每个技能暴露为一个独立工具（name + description 常驻上下文，正文按需懒加载），
    与 Claude Code / Codex 的技能目录一致；指令型技能使用空参数 schema，
    工具型技能使用其自身声明的 parameters schema。
    """
    tools: List[Dict[str, Any]] = []
    for spec in _REGISTRY.values():
        if spec["type"] == "tool":
            params = spec.get("parameters", {"type": "object", "properties": {}})
        else:
            params = {"type": "object", "properties": {}}
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": params,
                },
            }
        )
    return tools


def is_skill_tool(name: str) -> bool:
    """该工具名是否属于已发现的技能（白名单内）。"""
    return name in _REGISTRY


def list_skills() -> List[Dict[str, Any]]:
    """列出已发现的技能（供管理界面 / 调试使用）。"""
    return [
        {"name": s["name"], "type": s["type"], "description": s["description"]}
        for s in _REGISTRY.values()
    ]


def invoke_skill(
    name: str, params: Dict[str, Any], space_id: str = "__default__"
) -> Dict[str, Any]:
    """调用一个已注册技能，返回其结构化结果。

    * 指令型：返回 SKILL.md 正文（instructions），由模型照着用既有工具执行。
    * 工具型：subprocess 执行命令（stdin=JSON 参数，env X_SPACE_KEY=space_id），
      stdout 解析为 JSON 回灌模型。
    """
    spec = _REGISTRY.get(name)
    if spec is None:
        return {"success": False, "error": f"未知或未启用的技能: {name}"}

    # —— 指令型：懒加载正文，作为工作指引回灌 —— #
    if spec["type"] == "instruction":
        return {
            "success": True,
            "skill": name,
            "type": "instruction",
            "instructions": spec["body"],
        }

    # —— 工具型：subprocess 执行 —— #
    cmd = _resolve_command(spec["command"])
    env = dict(os.environ)
    env["X_SPACE_KEY"] = space_id or ""
    cwd = spec["dir"]

    try:
        proc = subprocess.run(
            cmd,
            input=json.dumps(params, ensure_ascii=False).encode("utf-8"),
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=spec.get("timeout", 60),
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"技能 '{name}' 执行超时（>{spec.get('timeout', 60)}s）",
        }
    except Exception as exc:  # 防御性兜底
        return {"success": False, "error": f"技能 '{name}' 执行异常: {exc}"}

    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()[:800]
        return {
            "success": False,
            "error": f"技能 '{name}' 退出码 {proc.returncode}: {err}",
        }

    out = (proc.stdout or b"").decode("utf-8", "replace").strip()
    if not out:
        return {"success": True, "output": ""}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"success": True, "output": out}


__all__ = [
    "SKILLS_DIR",
    "get_skill_tools",
    "is_skill_tool",
    "invoke_skill",
    "list_skills",
    "reload_skills",
    "scan_skills",
    "set_skill_enabled",
]
