"""Agent 代码执行工具（run_python）—— 受控沙箱式 Python 执行。

设计
----
Agent（LLM）生成 Python 代码后，经本工具在**独立工作区**中执行：

* **工作区隔离**：每次执行使用 ``data/code_exec/<space_id>/<uuid>/`` 独立目录，
  代码写入 ``main.py``，子进程 cwd 即工作区——产物文件自然落盘、可跨轮复用。
* **工作区复用**：返回 ``workspaceId``，Agent 下一轮可传入同一 ID 继续迭代
  （改代码重跑 / import 上一轮生成的模块），实现多轮编码闭环。
* **安全策略**：任意代码执行属不可逆操作，``policy=dangerous`` —— auto/manual
  模式 fail-closed 直接拒绝，strict 模式经人工审批后放行（复用既有三级审批矩阵）。
* **资源控制**：超时钳制（默认 30s、上限 120s，超时杀进程）；stdout/stderr
  UTF-8 解码 + 截断（各 8K 字符），防止巨量输出打爆上下文。
* **路径穿越防护**：``workspace`` 参数必须匹配 uuid hex 模式，杜绝 ``../`` 逃逸。
* **保留策略**：每个空间最多保留 20 个工作区，超出按 mtime 清理最旧目录。

局限（诚实声明）：这是「进程级隔离 + 审批门禁」，不是 OS 级容器沙箱——
经审批执行的代码以宿主 Python 运行，可访问本机依赖。审批门禁（dangerous
fail-closed）正是为此存在。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from .. import config
from ..tool_registry import POLICY_DANGEROUS, register_tool

# ---- 常量：资源控制 ---- #
DEFAULT_TIMEOUT_S = 30       # 默认超时（秒）
MAX_TIMEOUT_S = 120          # 超时上限
MAX_OUTPUT_CHARS = 8000      # stdout / stderr 各自的截断长度
MAX_CODE_CHARS = 100_000     # 代码长度上限（~100K 字符，防 prompt 注入巨块）
MAX_WORKSPACES_PER_SPACE = 20  # 每空间保留的工作区数

# 工作区 ID 必须是 uuid hex（8-32 个十六进制字符），杜绝路径穿越
_WS_ID_RE = re.compile(r"^[0-9a-f]{8,32}$")


def _workspace_root(space_id: str) -> Path:
    root = Path(config.DATA_DIR) / "code_exec" / space_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_workspace(space_id: str, requested: Optional[str]) -> Path:
    """解析工作区目录：显式复用（校验格式）或新建。"""
    root = _workspace_root(space_id)
    if requested:
        if not _WS_ID_RE.match(requested):
            raise ValueError(
                f"非法 workspace ID：{requested!r}（须为工具返回的 workspaceId）"
            )
        ws = root / requested
        if not ws.is_dir():
            raise ValueError(f"工作区不存在或已清理：{requested}")
        return ws
    ws = root / uuid.uuid4().hex
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _prune_workspaces(space_id: str, keep: int = MAX_WORKSPACES_PER_SPACE) -> None:
    """每空间只保留最近 ``keep`` 个工作区（按目录 mtime），清理更旧的。"""
    try:
        root = Path(config.DATA_DIR) / "code_exec" / space_id
        if not root.is_dir():
            return
        dirs = [d for d in root.iterdir() if d.is_dir()]
        if len(dirs) <= keep:
            return
        for d in sorted(dirs, key=lambda p: p.stat().st_mtime, reverse=True)[keep:]:
            for f in d.iterdir():
                try:
                    f.unlink()
                except OSError:
                    pass
            try:
                d.rmdir()
            except OSError:
                pass
    except OSError:
        pass  # 清理失败不影响主流程


def _list_files(ws: Path) -> list:
    """列出工作区文件（相对路径 + 字节数），供 Agent 感知产物。"""
    files = []
    try:
        for p in sorted(ws.rglob("*")):
            if p.is_file():
                files.append(
                    {"name": str(p.relative_to(ws)), "bytes": p.stat().st_size}
                )
                if len(files) >= 50:  # 最多列 50 个，防巨目录刷屏
                    break
    except OSError:
        pass
    return files


@register_tool(
    "run_python",
    description=(
        "在独立工作区中执行 Python 代码并返回结果。代码写入 main.py 后以子进程运行，"
        "工作目录即工作区（可直接读写文件、import 同目录模块）。"
        "返回 stdout/stderr/exitCode/产物文件列表与 workspaceId；"
        "传入上次返回的 workspaceId 可复用工作区实现多轮迭代编码。"
        "注意：属危险操作，需在严格审批模式下经用户批准后执行。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "要执行的完整 Python 代码（写入 main.py 运行）",
            },
            "timeout": {
                "type": "integer",
                "description": "执行超时（秒），默认 30，上限 120",
                "default": DEFAULT_TIMEOUT_S,
            },
            "workspace": {
                "type": "string",
                "description": "复用的工作区 ID（上一次执行返回的 workspaceId），不传则新建",
            },
        },
        "required": ["code"],
    },
    policy=POLICY_DANGEROUS,
)
def run_python(params: Dict[str, Any], space_id: Optional[str] = None) -> Dict[str, Any]:
    """执行 Agent 生成的 Python 代码（详见模块 docstring）。"""
    resolved_space = space_id if space_id is not None else "__default__"

    code = str(params.get("code") or "")
    if not code.strip():
        return {"success": False, "message": "code 为空"}

    if len(code) > MAX_CODE_CHARS:
        return {
            "success": False,
            "message": f"代码过长（{len(code)} 字符，上限 {MAX_CODE_CHARS}）",
        }

    try:
        timeout = int(params.get("timeout") or DEFAULT_TIMEOUT_S)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_S
    timeout = max(1, min(timeout, MAX_TIMEOUT_S))  # 钳制 [1, 120]

    try:
        ws = _resolve_workspace(resolved_space, params.get("workspace"))
    except ValueError as exc:
        return {"success": False, "message": str(exc)}

    script = ws / "main.py"
    try:
        script.write_text(code, encoding="utf-8")
    except OSError as exc:
        return {"success": False, "message": f"写入代码失败: {exc}"}

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"  # Windows 控制台编码兜底
    env["X_SPACE_KEY"] = resolved_space  # 与技能工具一致的约定

    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "main.py"],
            cwd=str(ws),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        duration_ms = int((time.time() - started) * 1000)
        stdout = (proc.stdout or "")[:MAX_OUTPUT_CHARS]
        stderr = (proc.stderr or "")[:MAX_OUTPUT_CHARS]
        truncated = len(proc.stdout or "") > MAX_OUTPUT_CHARS or len(proc.stderr or "") > MAX_OUTPUT_CHARS
        result: Dict[str, Any] = {
            "success": proc.returncode == 0,
            "exitCode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "durationMs": duration_ms,
            "workspaceId": ws.name,
            "files": _list_files(ws),
        }
        if truncated:
            result["truncated"] = True
            result["message"] = f"输出超过 {MAX_OUTPUT_CHARS} 字符已截断"
        return result
    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - started) * 1000)
        return {
            "success": False,
            "timeout": True,
            "message": f"执行超时（{timeout}s）已终止进程",
            "durationMs": duration_ms,
            "workspaceId": ws.name,
            "files": _list_files(ws),
        }
    except OSError as exc:
        return {"success": False, "message": f"启动子进程失败: {exc}"}
    finally:
        _prune_workspaces(resolved_space)


__all__ = ["run_python"]
