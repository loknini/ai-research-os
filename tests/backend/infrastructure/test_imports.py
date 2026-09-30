import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "case_module",
    [
        pytest.param(
            "tests.backend._cases.infrastructure.case_backend_architecture",
            marks=[pytest.mark.fast, pytest.mark.core],
            id="backend-architecture",
        ),
        pytest.param(
            "tests.backend._cases.infrastructure.case_package_imports",
            marks=[pytest.mark.fast, pytest.mark.core],
            id="package-imports",
        ),
        pytest.param(
            "tests.backend._cases.infrastructure.case_space",
            marks=pytest.mark.core,
            id="space-and-admin-boundaries",
        ),
    ],
)
def test_architecture_and_boundaries(case_module: str, run_isolated_case) -> None:
    run_isolated_case(case_module)


@pytest.mark.fast
@pytest.mark.core
def test_rag_golden_cli_rejects_unknown_commands(project_root) -> None:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    help_result = subprocess.run(
        [sys.executable, "-m", "scripts.eval_rag_golden", "--help"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    unknown_result = subprocess.run(
        [sys.executable, "-m", "scripts.eval_rag_golden", "unknown-command"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert help_result.returncode == 0
    assert "build" in help_result.stdout and "gate" in help_result.stdout
    assert unknown_result.returncode == 2
    assert "invalid choice" in unknown_result.stderr
