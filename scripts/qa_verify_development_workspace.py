#!/usr/bin/env python3
"""Offline QA for the isolated autonomous development workspace."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="qa_development_")
os.environ["DATA_DIR"] = str(Path(TEMP.name) / "data")

from backend.server import agent_teams, development_runner
from backend.server.development_workspace import (
    WorkspaceError, apply_workspace, commit_iteration, prepare_workspace,
    safe_path, validate_project, workspace_diff, write_files,
)
from backend.server.llm import llm_client
from scripts import database

passed = 0
failed = 0


def check(condition: bool, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"[PASS] {label}")
    else:
        failed += 1
        print(f"[FAIL] {label}")


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return result.stdout.strip()


def workspace_checks(root: Path) -> None:
    source = root / "plain"
    source.mkdir()
    (source / "main.py").write_text("print('old')\n", encoding="utf-8")
    project = {"id": "plain-project", "name": "Plain", "localPath": str(source)}
    validation = validate_project(project)
    check(validation["kind"] == "directory", "非 Git 项目识别为受控副本")
    snapshot = prepare_workspace(project, "space-a", "plain-run")
    write_files(snapshot, [{"path": "main.py", "content": "print('new')\n"}])
    recovered = prepare_workspace(project, "space-a", "plain-run")
    check(recovered["baseRevision"] == snapshot["baseRevision"] and
          "new" in (Path(recovered["workspacePath"]) / "main.py").read_text(),
          "准备阶段可从服务器元数据幂等恢复而不覆盖 Agent 修改")
    diff = workspace_diff(snapshot)
    check(diff["files"] == ["main.py"] and "print('new')" in diff["patch"],
          "受控副本生成真实差异")
    try:
        safe_path(Path(snapshot["workspacePath"]), "../outside.py")
        check(False, "目录穿越被拒绝")
    except WorkspaceError:
        check(True, "目录穿越被拒绝")
    result = apply_workspace(snapshot, diff["baseRevision"], diff["diffDigest"])
    check(result["applied"] and "new" in (source / "main.py").read_text(encoding="utf-8"),
          "显式应用把差异写回非 Git 项目")

    conflict_source = root / "conflict"
    conflict_source.mkdir()
    (conflict_source / "a.txt").write_text("base", encoding="utf-8")
    conflict = prepare_workspace(
        {"id": "conflict", "name": "Conflict", "localPath": str(conflict_source)},
        "space-a", "conflict-run")
    write_files(conflict, [{"path": "a.txt", "content": "agent"}])
    conflict_diff = workspace_diff(conflict)
    (conflict_source / "a.txt").write_text("user", encoding="utf-8")
    try:
        apply_workspace(conflict, conflict_diff["baseRevision"], conflict_diff["diffDigest"])
        check(False, "源文件变化时拒绝应用")
    except WorkspaceError:
        check((conflict_source / "a.txt").read_text() == "user", "源文件变化时拒绝应用")

    repo = root / "git"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "qa@example.invalid")
    git(repo, "config", "user.name", "QA")
    (repo / "value.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", "value.txt"); git(repo, "commit", "-m", "base")
    git_snapshot = prepare_workspace(
        {"id": "git-project", "name": "Git", "localPath": str(repo)},
        "space-a", "git-run")
    write_files(git_snapshot, [{"path": "value.txt", "content": "agent\n"}])
    commit_iteration(git_snapshot, 1)
    git_diff = workspace_diff(git_snapshot)
    check(git_diff["files"] == ["value.txt"] and (repo / "value.txt").read_text() == "base\n",
          "Git worktree 不直接修改原分支")
    apply_workspace(git_snapshot, git_diff["baseRevision"], git_diff["diffDigest"])
    check((repo / "value.txt").read_text() == "agent\n", "Git 差异经显式应用写回原分支")


async def runner_checks(root: Path) -> None:
    await database.init_db()
    source = root / "runner-project"
    (source / "tests").mkdir(parents=True)
    (source / "calc.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
    (source / "tests" / "test_calc.py").write_text(
        "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n"
        "    def test_add(self): self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8")
    project = {
        "id": "runner-project", "name": "Runner", "description": "", "techStack": ["Python"],
        "status": "design", "localPath": str(source), "features": [], "milestones": [],
        "aiGeneratedCode": False,
    }
    check(await database.insert_project(project, "space-runner"), "研发 QA 项目可落库")
    team = next(item for item in agent_teams.list_builtin_teams()
                if item["id"] == "builtin-software-development")
    original = llm_client.call_llm

    def fake_llm(messages, **_kwargs):
        system = messages[0]["content"]
        if "需求与代码分析师" in system:
            return json.dumps({"summary": "修复加法", "successCriteria": ["测试通过"],
                               "filesToChange": ["calc.py"], "risks": []}, ensure_ascii=False)
        if "资深软件工程师" in system:
            return json.dumps({"summary": "实现加法", "files": [{"path": "calc.py",
                "content": "def add(a, b):\n    return a + b\n"}]}, ensure_ascii=False)
        if "测试工程师" in system:
            return json.dumps({"summary": "现有测试足够", "files": []}, ensure_ascii=False)
        return json.dumps({"accepted": True, "summary": "测试通过", "unmetCriteria": [],
                           "risks": []}, ensure_ascii=False)

    llm_client.call_llm = fake_llm
    try:
        run_id = await development_runner.submit(
            "space-runner", await database.get_project_by_id("runner-project", "space-runner"),
            "让 add 返回正确结果", team, ["unittest 通过"], 3, 5,
            {"workspaceWrites": True, "verificationCommands": True})
        deadline = time.time() + 30
        run = None
        while time.time() < deadline:
            run = await database.get_agent_run(run_id, "space-runner")
            if run and run["status"] in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.2)
        if not run or run["status"] != "completed":
            print("[DEBUG] runner state:", json.dumps(run, ensure_ascii=False, default=str))
        check(bool(run and run["status"] == "completed" and run["phase"] == "awaiting_apply"),
              "Runner 完成分析、写码、测试与审查闭环")
        steps = await database.list_development_steps(run_id, "space-runner")
        if len(steps) != 4:
            print("[DEBUG] steps:", json.dumps(steps, ensure_ascii=False, default=str))
        check([step["phase"] for step in steps] ==
              ["analyzing", "implementing", "testing", "reviewing"], "四阶段步骤完整持久化")
        diff = workspace_diff(run["workspaceSnapshot"])
        check("calc.py" in diff["files"] and "return a + b" in diff["patch"],
              "Runner 产物为可审阅真实代码差异")
        check("return 0" in (source / "calc.py").read_text(), "完成运行不会自动修改原项目")
        apply_workspace(run["workspaceSnapshot"], diff["baseRevision"], diff["diffDigest"])
        check("return a + b" in (source / "calc.py").read_text(), "用户显式应用后原项目更新")
    finally:
        llm_client.call_llm = original


def api_checks() -> None:
    from fastapi.testclient import TestClient
    from backend.server.main import app

    original_spawn = development_runner.spawn
    development_runner.spawn = lambda *_args, **_kwargs: None
    try:
        with TestClient(app) as client:
            headers = {"X-Space-Key": "space-runner"}
            validated = client.post(
                "/api/projects/runner-project/workspace/validate", headers=headers, json={})
            check(validated.status_code == 200 and validated.json()["workspace"]["kind"] == "directory",
                  "工作区校验 API 返回真实目录类型")
            invalid_config = client.put(
                "/api/projects/runner-project/development-config", headers=headers,
                json={"ignorePaths": ["../outside"]})
            check(invalid_config.status_code == 400, "研发配置 API 拒绝越界忽略路径")
            created = client.post(
                "/api/projects/runner-project/development-runs", headers=headers,
                json={"goal": "API smoke", "teamId": "builtin-software-development",
                      "successCriteria": ["验证通过"], "maxIterations": 2,
                      "maxDurationMinutes": 5,
                      "authorization": {"workspaceWrites": True,
                                        "verificationCommands": True}})
            run_id = created.json().get("runId")
            detail = client.get(f"/api/development/runs/{run_id}", headers=headers)
            isolated = client.get(
                f"/api/development/runs/{run_id}", headers={"X-Space-Key": "other-space"})
            check(created.status_code == 200 and detail.status_code == 200
                  and detail.json()["run"]["runKind"] == "development",
                  "研发创建与详情 API 保持 runKind 契约")
            check(isolated.status_code == 404, "研发运行 API 按 space-key 隔离")
            cancelled = client.post(f"/api/development/runs/{run_id}/cancel", headers=headers)
            check(cancelled.status_code == 200 and cancelled.json()["cancelled"],
                  "排队中的研发运行可通过 API 取消")
    finally:
        development_runner.spawn = original_spawn


async def main() -> None:
    root = Path(TEMP.name)
    workspace_checks(root)
    await runner_checks(root)
    await asyncio.to_thread(api_checks)
    await database.init_db()
    check(True, "研发数据迁移可重复初始化")
    print(f"\nDevelopment workspace QA: {passed}/{passed + failed} passed")
    TEMP.cleanup()
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
