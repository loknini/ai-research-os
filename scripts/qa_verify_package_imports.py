#!/usr/bin/env python3
"""Verify the project's package-import and subprocess-entrypoint contract."""
from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_MODULES = (
    "scripts.fetch_arxiv",
    "scripts.citation_service",
    "scripts.formula_service",
    "scripts.summarize_paper",
    "scripts.backfill_vec",
    "scripts.eval_rag_golden",
)


def fail(message: str) -> None:
    raise AssertionError(message)


def verify_no_sys_path_mutation() -> None:
    violations: list[str] = []
    for source_root in (PROJECT_ROOT / "backend", PROJECT_ROOT / "scripts"):
        for path in source_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                owner = node.func.value
                if (
                    node.func.attr in {"insert", "append"}
                    and isinstance(owner, ast.Attribute)
                    and isinstance(owner.value, ast.Name)
                    and owner.value.id == "sys"
                    and owner.attr == "path"
                ):
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
    if violations:
        fail("发现 sys.path 注入：" + ", ".join(violations))


def verify_modules_are_importable() -> None:
    for module_name in PUBLIC_MODULES:
        importlib.import_module(module_name)


def verify_backend_subprocess_contract() -> None:
    from backend.server import config, helpers

    completed = subprocess.CompletedProcess([], 0, '{"success": true}', "")
    with patch.object(helpers.subprocess, "run", return_value=completed) as mocked_run:
        result = helpers.run_script("citation_service.py", "unknown")

    if result != {"success": True}:
        fail(f"run_script 返回值异常：{result!r}")

    command = mocked_run.call_args.args[0]
    kwargs = mocked_run.call_args.kwargs
    expected = [sys.executable, "-m", "scripts.citation_service", "unknown"]
    if command != expected:
        fail(f"子进程命令异常：{command!r}")
    if Path(kwargs["cwd"]).resolve() != config.PROJECT_ROOT.resolve():
        fail(f"子进程工作目录异常：{kwargs['cwd']!r}")
    if kwargs["env"].get("PYTHONPATH") != os.environ.get("PYTHONPATH"):
        fail("run_script 不应修改 PYTHONPATH")


def verify_direct_execution_guidance() -> None:
    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    for module_name in PUBLIC_MODULES:
        script_path = PROJECT_ROOT / (module_name.replace(".", "/") + ".py")
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
            timeout=20,
        )
        guidance = f"python -m {module_name}"
        if proc.returncode != 2 or guidance not in proc.stderr:
            fail(
                f"{script_path.relative_to(PROJECT_ROOT)} 的直接执行提示异常："
                f"returncode={proc.returncode}, stderr={proc.stderr!r}"
            )


def main() -> int:
    checks = (
        ("无 sys.path 注入", verify_no_sys_path_mutation),
        ("公共脚本可按包导入", verify_modules_are_importable),
        ("后端以 python -m 启动脚本", verify_backend_subprocess_contract),
        ("错误入口给出迁移提示", verify_direct_execution_guidance),
    )
    with tempfile.TemporaryDirectory(prefix="qa_package_imports_") as temp_dir:
        os.environ["DATA_DIR"] = temp_dir
        for label, check in checks:
            try:
                check()
            except Exception as exc:
                print(f"[FAIL] {label}: {exc}")
                return 1
            print(f"[PASS] {label}")
    print(f"\n包导入约定验证通过（{len(checks)} 项）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
