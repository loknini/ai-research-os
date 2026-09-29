"""FastAPI 后端共享辅助函数。

``run_script`` 是对 ``subprocess`` 的轻量复用封装：执行指定的 ``scripts`` 包模块，
并解析其写到 stdout 的 JSON。

SwanLab、引用、Obsidian 和公式等外部集成继续使用轻量子进程，不强行改成可导入函数；
这样既降低迁移风险，又能让 API 层集中在常驻 FastAPI 进程中。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .core import config


def run_script(
    script_name: str,
    *args: str,
    timeout: int = 60,
    env_extra: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """用位置参数运行 ``scripts/<script_name>`` 并返回解析后的 JSON。

    脚本应打印一个 JSON 对象，也允许对象嵌在 stdout 中。任何失败都返回
    ``{"success": False, "error": <reason>}``，而不是抛出异常，使路由能向前端转发
    干净的 JSON 错误。额外环境变量会合并进子进程环境，主要用于传递空间标识。
    """
    script_path = config.SCRIPTS_DIR / script_name
    if not script_path.exists():
        return {"success": False, "error": f"Script not found: {script_name}"}

    module_name = f"scripts.{script_path.stem}"
    cmd = [sys.executable, "-m", module_name, *[str(a) for a in args]]
    env = os.environ.copy()
    env["DATA_DIR"] = str(config.DATA_DIR)
    if env_extra:
        env.update(env_extra)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(config.PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Script timed out after {timeout}s: {script_name}"}
    except Exception as exc:  # pragma: no cover - defensive
        return {"success": False, "error": str(exc)}

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        return {
            "success": False,
            "error": stderr or f"Script exited with code {proc.returncode}",
        }

    out = (proc.stdout or "").strip()
    if not out:
        return {"success": True, "data": None}

    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # 完整解析失败时，回退为提取输出中的最后一个 JSON 对象。
        match = re.search(r"\{.*\}", out, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {"success": True, "data": out}


__all__ = ["run_script"]
