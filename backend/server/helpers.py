"""Shared helpers for the FastAPI backend.

``run_script`` is a thin, reusable wrapper around ``subprocess`` that executes a
legacy ``scripts/*.py`` CLI exactly the way the old Vite middleware did
(``spawn('python', ['scripts/x.py', <command>, <json>])``) and parses the JSON
it prints to stdout.

Per the agreed decision, the *external* integrations (swanlab / citation /
obsidian / formula) keep these lightweight subprocess calls instead of being
refactored into importable functions — this minimises risk while still moving
the API layer into a single resident FastAPI process.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import config


def run_script(
    script_name: str,
    *args: str,
    timeout: int = 60,
    env_extra: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run ``scripts/<script_name>`` with positional ``args`` and return parsed JSON.

    The script is expected to print a single JSON object (or an object embedded
    in its stdout) which is parsed and returned.  On any failure a
    ``{"success": False, "error": <reason>}`` dict is returned instead of raising,
    so routers can forward a clean JSON error to the frontend.

    Args:
        script_name: File name under ``config.SCRIPTS_DIR``.
        *args: Positional CLI arguments forwarded to the script.
        timeout: Subprocess timeout in seconds.
        env_extra: Extra environment variables (e.g. ``{"SPACE_ID": space_id}``)
            merged into the child process environment for space isolation.
    """
    script_path = config.SCRIPTS_DIR / script_name
    if not script_path.exists():
        return {"success": False, "error": f"Script not found: {script_name}"}

    cmd = [sys.executable, str(script_path), *[str(a) for a in args]]
    env = os.environ.copy()
    env["DATA_DIR"] = str(config.DATA_DIR)
    # Ensure the script can import its sibling modules (database, etc.).
    env["PYTHONPATH"] = str(config.SCRIPTS_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
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
        # Fall back to extracting the last JSON object from the output.
        match = re.search(r"\{.*\}", out, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {"success": True, "data": out}


__all__ = ["run_script"]
