"""Durable fixed-state development runner.

The runner intentionally does not expose a shell to the model. Models return
structured file snapshots; the server validates paths, writes atomically and
runs only detected/configured Python and Node verification commands.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import agent_teams, db
from .development_workspace import (
    WorkspaceError, commit_iteration, detect_commands, prepare_workspace,
    safe_path, workspace_diff, write_files,
)
from .llm import llm_client

LEASE_MS = 30000
POLL_SECONDS = 2.0
MAX_LOG_CHARS = 120000
_OWNER = f"{os.getpid()}-{uuid.uuid4()}"
_ACTIVE: Dict[str, threading.Thread] = {}
_CANCEL: Dict[str, threading.Event] = {}
_COORDINATOR: Optional[threading.Thread] = None
_STOP = threading.Event()
_ACTIVE_LOCK = threading.Lock()


class DevelopmentError(RuntimeError):
    pass


def _parse_json(text: Optional[str]) -> Dict[str, Any]:
    if not text:
        raise DevelopmentError("LLM 未返回可用结果，请检查模型配置")
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", candidate)
        if not match:
            raise DevelopmentError("LLM 没有返回要求的 JSON")
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise DevelopmentError("LLM 返回了无效 JSON") from exc
    if not isinstance(value, dict):
        raise DevelopmentError("LLM JSON 顶层必须是对象")
    return value


def _repo_context(root: Path, ignored: Optional[List[str]] = None) -> str:
    names: List[str] = []
    snippets: List[str] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in {".git", "node_modules", ".venv", "dist", "build", "__pycache__"}
               for part in relative.parts):
            continue
        lower_name = relative.name.lower()
        if (lower_name.startswith(".env") and lower_name != ".env.example") \
                or lower_name in {"credentials.json", "secrets.json", "id_rsa", "id_ed25519"} \
                or lower_name.endswith((".pem", ".key", ".p12", ".pfx")):
            continue
        normalized = relative.as_posix()
        if any(normalized == item.rstrip("/") or normalized.startswith(item.rstrip("/") + "/")
               for item in (ignored or [])):
            continue
        names.append(relative.as_posix())
        if len(snippets) >= 24 or total >= 80000 or path.stat().st_size > 200000:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")[:8000]
        except OSError:
            continue
        snippets.append(f"### {relative.as_posix()}\n```\n{content}\n```")
        total += len(content)
    return "## 文件清单\n" + "\n".join(names[:1000]) + "\n\n## 关键文件\n" + "\n\n".join(snippets)


def _node(team: Dict[str, Any], stage: str) -> Dict[str, Any]:
    return next(node for node in team["nodes"] if node.get("stage") == stage)


async def _call_node(node: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    text = await asyncio.to_thread(
        llm_client.call_llm,
        [{"role": "system", "content": node["systemPrompt"]},
         {"role": "user", "content": prompt}],
        model=node.get("model"), temperature=node.get("temperature"),
        max_tokens=node.get("maxTokens"),
    )
    return _parse_json(text)


async def _event(run_id: str, space_id: str, event_type: str, **data: Any) -> None:
    await db.database.add_agent_run_event(run_id, space_id, {"type": event_type, **data})


async def _step(run_id: str, space_id: str, iteration: int, phase: str,
                node_id: str, prompt: str, attempt: int = 1) -> tuple[str, Dict[str, Any]]:
    step_id = await db.database.create_development_step(
        run_id, space_id, iteration, phase, node_id, prompt[:4000], attempt=attempt)
    await _event(run_id, space_id, "development_phase_start", phase=phase,
                 iteration=iteration, nodeId=node_id)
    try:
        result = await _call_node(_CURRENT_TEAMS[run_id][node_id], prompt)
        if _CANCEL.get(run_id, threading.Event()).is_set() \
                or await db.database.get_agent_run_status(run_id, space_id) == "cancelled":
            raise DevelopmentError("运行已取消，模型迟到结果已丢弃")
        await db.database.finish_development_step(step_id, run_id, space_id, "completed", result)
        await _event(run_id, space_id, "development_phase_complete", phase=phase,
                     iteration=iteration, nodeId=node_id)
        return step_id, result
    except Exception as exc:
        await db.database.finish_development_step(
            step_id, run_id, space_id, "failed", error_message=str(exc))
        await _event(run_id, space_id, "development_phase_failed", phase=phase,
                     iteration=iteration, nodeId=node_id, error=str(exc))
        raise


_CURRENT_TEAMS: Dict[str, Dict[str, Dict[str, Any]]] = {}


def _requested_context(workspace: Path, snapshot: Dict[str, Any], request: Any) -> str:
    """Resolve a bounded model context request with the same workspace path policy."""
    if not isinstance(request, dict):
        return ""
    sections: List[str] = []
    total = 0
    for relative in (request.get("files") or [])[:20]:
        if not isinstance(relative, str):
            continue
        normalized = Path(relative.replace("\\", "/")).as_posix()
        if any(normalized == value.rstrip("/") or normalized.startswith(value.rstrip("/") + "/")
               for value in (snapshot.get("ignorePaths") or [])):
            continue
        try:
            path = safe_path(workspace, relative, allow_missing=False)
            if not path.is_file() or path.stat().st_size > 300000:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")[:16000]
        except (OSError, WorkspaceError):
            continue
        sections.append(f"### requested file: {normalized}\n```\n{content}\n```")
        total += len(content)
        if total >= 80000:
            break
    queries = [value.lower() for value in (request.get("search") or [])[:10]
               if isinstance(value, str) and 1 <= len(value) <= 200]
    if queries and total < 80000:
        hits: List[str] = []
        for path in workspace.rglob("*"):
            if len(hits) >= 80 or not path.is_file() or path.is_symlink() or path.stat().st_size > 300000:
                continue
            relative = path.relative_to(workspace).as_posix()
            if any(relative == value.rstrip("/") or relative.startswith(value.rstrip("/") + "/")
                   for value in (snapshot.get("ignorePaths") or [])):
                continue
            try:
                safe_path(workspace, relative, allow_missing=False)
                content = path.read_text(encoding="utf-8", errors="replace")
            except (OSError, WorkspaceError):
                continue
            for line_number, line in enumerate(content.splitlines(), 1):
                if any(query in line.lower() for query in queries):
                    hits.append(f"{relative}:{line_number}: {line[:500]}")
                    if len(hits) >= 80:
                        break
        if hits:
            sections.append("### search results\n" + "\n".join(hits))
    return "\n\n".join(sections)[:100000]


def _validated_commands(snapshot: Dict[str, Any], config_value: Dict[str, Any]) -> List[List[str]]:
    configured = (config_value.get("testCommands") or []) + (config_value.get("buildCommands") or [])
    commands = configured or snapshot.get("commands") or []
    allowed_names = {"python", "python3", "py", "node", "npm", "npm.cmd", "pnpm", "pnpm.cmd",
                     "yarn", "yarn.cmd"}
    result: List[List[str]] = []
    for command in commands:
        if not isinstance(command, list) or not command or any(not isinstance(v, str) for v in command):
            raise DevelopmentError("验证命令必须是非空参数数组")
        executable = Path(command[0]).name.lower()
        if executable not in allowed_names and Path(command[0]).resolve() != Path(os.sys.executable).resolve():
            raise DevelopmentError(f"不允许执行命令: {command[0]}")
        if any(any(marker in arg for marker in ("|", "&&", ";", ">", "<", "`", "$("))
               for arg in command):
            raise DevelopmentError("验证命令不能包含 shell 操作符")
        if executable.startswith(("npm", "pnpm", "yarn")):
            if len(command) < 3 or command[1] != "run" or not re.fullmatch(r"[\w:.-]+", command[2]):
                raise DevelopmentError("Node 仅允许运行 package.json 中的 script")
        elif executable.startswith(("python", "py")) or Path(command[0]).resolve() == Path(os.sys.executable).resolve():
            if len(command) < 3 or command[1] != "-m" or command[2] not in {"pytest", "unittest"}:
                raise DevelopmentError("Python 仅允许 pytest 或 unittest 模块")
        result.append(command)
    return result


async def _run_command(run_id: str, space_id: str, workspace: Path,
                       command: List[str], timeout: int = 600) -> Dict[str, Any]:
    executable = shutil.which(command[0]) or command[0]
    command = [executable, *command[1:]]
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    with tempfile.TemporaryFile(mode="w+b") as output_file:
        process = subprocess.Popen(
            command, cwd=str(workspace), shell=False, stdout=output_file,
            stderr=subprocess.STDOUT, creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        started = time.monotonic()
        while process.poll() is None:
            if _CANCEL.get(run_id, threading.Event()).is_set() \
                    or await db.database.get_agent_run_status(run_id, space_id) == "cancelled":
                process.kill()
                raise DevelopmentError("运行已取消")
            if time.monotonic() - started > timeout:
                process.kill()
                raise DevelopmentError("验证命令超时")
            await asyncio.sleep(0.3)
        output_file.seek(0)
        output = output_file.read().decode("utf-8", errors="replace")
    return {"command": command, "exitCode": process.returncode,
            "output": output[-MAX_LOG_CHARS:], "durationMs": int((time.monotonic() - started) * 1000)}


async def _execute(run_id: str, space_id: str) -> None:
    if not await db.database.claim_development_run(run_id, space_id, _OWNER, LEASE_MS):
        return
    run = await db.database.get_agent_run(run_id, space_id)
    if not run:
        return
    team = run.get("teamSnapshot") or {}
    _CURRENT_TEAMS[run_id] = {node["id"]: node for node in team.get("nodes", [])}
    cancel = _CANCEL.setdefault(run_id, threading.Event())
    started = time.monotonic()
    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(LEASE_MS / 3000)
            if not await db.database.renew_development_lease(run_id, space_id, _OWNER, LEASE_MS):
                _CANCEL.setdefault(run_id, threading.Event()).set()
                return
    lease_task = asyncio.create_task(heartbeat())
    try:
        project = await db.database.get_project_by_id(run["projectId"], space_id)
        if not project:
            raise DevelopmentError("项目不存在或不属于当前空间")
        snapshot = run.get("workspaceSnapshot")
        if not snapshot:
            await db.database.update_agent_run(run_id, space_id, phase="preparing")
            await _event(run_id, space_id, "development_phase_start", phase="preparing", iteration=0)
            snapshot = await asyncio.to_thread(prepare_workspace, project, space_id, run_id)
            if not project.get("localPath"):
                await db.database.update_project(project["id"], {"localPath": snapshot["sourcePath"]}, space_id)
            await db.database.update_agent_run(run_id, space_id, workspace_snapshot=snapshot,
                                               checkpoint={"lastSafePhase": "prepared"})
            await _event(run_id, space_id, "development_phase_complete", phase="preparing", iteration=0)
        workspace = Path(snapshot["workspacePath"])
        project_config = project.get("developmentConfig") or {}
        iteration = max(1, int(run.get("iteration") or 0) + 1)
        plan = (run.get("checkpoint") or {}).get("plan")
        feedback = (run.get("checkpoint") or {}).get("feedback", "")
        while iteration <= int(run.get("maxIterations") or 12):
            now = int(time.time() * 1000)
            if cancel.is_set() or await db.database.get_agent_run_status(run_id, space_id) == "cancelled":
                return
            if now >= int(run.get("deadlineAt") or now + 1):
                break
            await db.database.renew_development_lease(run_id, space_id, _OWNER, LEASE_MS)
            await db.database.update_agent_run(run_id, space_id, iteration=iteration,
                                               budget_used_ms=int((time.monotonic() - started) * 1000))
            context = await asyncio.to_thread(
                _repo_context, workspace, project_config.get("ignorePaths") or [])
            if not plan:
                await db.database.update_agent_run(run_id, space_id, phase="analyzing")
                _, plan = await _step(
                    run_id, space_id, iteration, "analyzing", _node(team, "analysis")["id"],
                    f"目标：{run['requirement']}\n用户成功标准：{(run.get('inputContext') or {}).get('successCriteria', [])}\n\n{context}\n\n"
                    "只返回 JSON：{summary, successCriteria: string[], filesToChange: string[], risks: string[]}。")
                await db.database.add_development_artifact(
                    run_id, space_id, iteration, "plan", json.dumps(plan, ensure_ascii=False, indent=2))
            await db.database.update_agent_run(run_id, space_id, phase="implementing",
                                               checkpoint={"plan": plan, "feedback": feedback,
                                                           "lastSafePhase": "analysis"})
            _, implementation = await _step(
                run_id, space_id, iteration, "implementing", _node(team, "implementation")["id"],
                f"目标：{run['requirement']}\n计划：{json.dumps(plan, ensure_ascii=False)}\n"
                f"上一轮反馈：{feedback or '无'}\n\n{context}\n\n"
                "完成目标所需的源码修改。只返回 JSON：{summary, files:[{path,content}|{path,delete:true}], "
                "needsContext?:{files:string[],search:string[]}}。content 必须是文件的完整最终内容；"
                "不要输出未修改文件。如果关键文件内容不可见，先只用 needsContext 请求读取或搜索。")
            if implementation.get("needsContext"):
                requested = await asyncio.to_thread(
                    _requested_context, workspace, snapshot, implementation["needsContext"])
                if requested:
                    await _event(run_id, space_id, "development_context_read", iteration=iteration,
                                 request=implementation["needsContext"])
                    _, implementation = await _step(
                        run_id, space_id, iteration, "implementing",
                        _node(team, "implementation")["id"],
                        f"目标：{run['requirement']}\n计划：{json.dumps(plan, ensure_ascii=False)}\n"
                        f"上一轮反馈：{feedback or '无'}\n\n## 按请求补充的可信上下文\n{requested}\n\n"
                        "现在返回最终 JSON：{summary, files:[{path,content}|{path,delete:true}]}。content 是完整文件内容。",
                        attempt=2)
            written = await asyncio.to_thread(write_files, snapshot, implementation.get("files") or [])
            await _event(run_id, space_id, "development_files_written", iteration=iteration, files=written)

            await db.database.update_agent_run(run_id, space_id, phase="testing")
            context = await asyncio.to_thread(
                _repo_context, workspace, project_config.get("ignorePaths") or [])
            refreshed = detect_commands(workspace)
            snapshot["commands"] = refreshed["commands"]
            _, testing = await _step(
                run_id, space_id, iteration, "testing", _node(team, "testing")["id"],
                f"目标：{run['requirement']}\n计划：{json.dumps(plan, ensure_ascii=False)}\n"
                f"已修改文件：{written}\n检测到的验证命令：{snapshot['commands']}\n\n{context}\n\n"
                "如缺少必要测试，请补充测试文件。只返回 JSON：{summary, files:[{path,content}]}；"
                "无需修改时 files 为空数组。")
            test_files = await asyncio.to_thread(write_files, snapshot, testing.get("files") or [])
            if test_files:
                refreshed = detect_commands(workspace)
                snapshot["runtime"] = refreshed["runtime"]
                snapshot["packageManager"] = refreshed["packageManager"]
                snapshot["commands"] = refreshed["commands"]
            commands = _validated_commands(snapshot, project_config)
            reports: List[Dict[str, Any]] = []
            if not commands:
                reports.append({"command": [], "exitCode": 1,
                                "output": "未检测到测试、构建或类型检查命令"})
            else:
                for command in commands:
                    report = await _run_command(run_id, space_id, workspace, command)
                    reports.append(report)
                    await db.database.add_development_artifact(
                        run_id, space_id, iteration, "command_log", report["output"],
                        metadata={"command": command, "exitCode": report["exitCode"],
                                  "durationMs": report["durationMs"]})
            tests_passed = bool(reports) and all(report["exitCode"] == 0 for report in reports)
            await _event(run_id, space_id, "development_tests_complete", iteration=iteration,
                         passed=tests_passed, reports=[{k: v for k, v in report.items() if k != "output"}
                                                       for report in reports])
            commit = await asyncio.to_thread(commit_iteration, snapshot, iteration)
            diff = await asyncio.to_thread(workspace_diff, snapshot)

            await db.database.update_agent_run(run_id, space_id, phase="reviewing")
            _, review = await _step(
                run_id, space_id, iteration, "reviewing", _node(team, "review")["id"],
                f"目标：{run['requirement']}\n成功标准：{plan.get('successCriteria', [])}\n"
                f"测试通过：{tests_passed}\n测试结果：{json.dumps(reports, ensure_ascii=False)[-30000:]}\n"
                f"变更摘要：{diff['patch'][-60000:]}\n\n"
                "只返回 JSON：{accepted:boolean, summary:string, unmetCriteria:string[], risks:string[]}。"
                "测试未通过时 accepted 必须为 false。")
            accepted = tests_passed and review.get("accepted") is True \
                and not (review.get("unmetCriteria") or [])
            await db.database.add_development_artifact(
                run_id, space_id, iteration, "review", json.dumps(review, ensure_ascii=False, indent=2),
                metadata={"commit": commit, "testsPassed": tests_passed})
            if accepted:
                summary = {"plan": plan, "review": review, "tests": reports,
                           "diff": {k: v for k, v in diff.items() if k != "patch"},
                           "changedFiles": diff["files"]}
                await db.database.update_agent_run(
                    run_id, space_id, checkpoint={"plan": plan, "review": review,
                                                  "lastSafePhase": "awaiting_apply"},
                    workspace_snapshot=snapshot,
                    budget_used_ms=int((time.monotonic() - started) * 1000))
                await db.database.finish_development_run(
                    run_id, space_id, _OWNER, "completed", "awaiting_apply", summary)
                return
            feedback = json.dumps({"tests": reports, "review": review}, ensure_ascii=False)[-40000:]
            await db.database.update_agent_run(
                run_id, space_id, checkpoint={"plan": plan, "feedback": feedback,
                                              "lastSafePhase": "review"},
                workspace_snapshot=snapshot)
            iteration += 1
        await db.database.finish_development_run(
            run_id, space_id, _OWNER, "failed", "budget_exhausted",
            error_message="研发预算已耗尽，可追加轮数和时间后继续")
    except Exception as exc:
        if await db.database.get_agent_run_status(run_id, space_id) != "cancelled":
            await db.database.finish_development_run(
                run_id, space_id, _OWNER, "failed", "failed", error_message=str(exc))
    finally:
        lease_task.cancel()
        _CURRENT_TEAMS.pop(run_id, None)
        _CANCEL.pop(run_id, None)
        with _ACTIVE_LOCK:
            _ACTIVE.pop(run_id, None)


def _thread_target(run_id: str, space_id: str) -> None:
    asyncio.run(_execute(run_id, space_id))


def spawn(run_id: str, space_id: str) -> None:
    with _ACTIVE_LOCK:
        existing = _ACTIVE.get(run_id)
        if existing and existing.is_alive():
            return
        thread = threading.Thread(target=_thread_target, args=(run_id, space_id), daemon=True,
                                  name=f"development-{run_id[:8]}")
        _CANCEL[run_id] = threading.Event()
        _ACTIVE[run_id] = thread
    thread.start()


async def submit(space_id: str, project: Dict[str, Any], goal: str,
                 team: Dict[str, Any], success_criteria: List[str],
                 max_iterations: int, max_duration_minutes: int,
                 authorization: Dict[str, Any]) -> str:
    run_id = str(uuid.uuid4())
    now = int(time.time() * 1000)
    created = await db.database.create_agent_run(
        run_id, space_id, project["id"], goal, [node["id"] for node in team["nodes"]],
        status="pending", team_id=team.get("id"), team_name=team.get("name"),
        team_snapshot=team, input_context={"kind": "software_project",
                                           "entityIds": [project["id"]],
                                           "successCriteria": success_criteria},
        run_kind="development", phase="queued", max_iterations=max_iterations,
        deadline_at=now + max_duration_minutes * 60 * 1000,
        checkpoint={}, authorization=authorization,
    )
    if created:
        await db.database.add_agent_run_event(
            run_id, space_id, {"type": "run_queued", "phase": "queued",
                               "message": "研发运行已进入队列"})
        spawn(run_id, space_id)
    return created


def cancel(run_id: str) -> None:
    signal = _CANCEL.get(run_id)
    if signal is not None:
        signal.set()


def _coordinator_loop() -> None:
    while not _STOP.wait(POLL_SECONDS):
        try:
            runs = asyncio.run(db.database.list_claimable_development_runs())
            for run in runs:
                spawn(run["id"], run["spaceId"])
        except Exception:
            continue


def start_development_runner() -> None:
    global _COORDINATOR
    if _COORDINATOR and _COORDINATOR.is_alive():
        return
    _STOP.clear()
    _COORDINATOR = threading.Thread(target=_coordinator_loop, daemon=True,
                                    name="development-coordinator")
    _COORDINATOR.start()


__all__ = ["cancel", "spawn", "start_development_runner", "submit"]
