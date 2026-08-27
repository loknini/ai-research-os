#!/usr/bin/env python3
"""Offline correctness QA for configurable expert teams and DAG execution."""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from backend.server import agent_runner, agent_service, agent_teams
from backend.server.main import app
from scripts import database

PASSED = 0
FAILED = 0


def check(condition: bool, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"[PASS] {label}")
    else:
        FAILED += 1
        print(f"[FAIL] {label}")


def simple_team(name: str = "测试团队") -> dict:
    return {
        "schemaVersion": 1, "name": name, "description": "offline QA", "category": "test",
        "acceptedContexts": ["generic", "papers"], "maxConcurrency": 2,
        "approvalMode": "manual", "outputNodeId": "join",
        "nodes": [
            {"id": "root-a", "name": "A", "description": "A", "systemPrompt": "A",
             "allowedTools": [], "model": None, "temperature": 0.2, "maxTokens": 200,
             "output": {"type": "text"}, "position": {"x": 0, "y": 0}},
            {"id": "root-b", "name": "B", "description": "B", "systemPrompt": "B",
             "allowedTools": [], "model": None, "temperature": 0.2, "maxTokens": 200,
             "output": {"type": "text"}, "position": {"x": 0, "y": 100}},
            {"id": "join", "name": "Join", "description": "join", "systemPrompt": "join",
             "allowedTools": [], "model": None, "temperature": 0.2, "maxTokens": 200,
             "output": {"type": "text"}, "position": {"x": 300, "y": 50}},
        ],
        "edges": [
            {"id": "b-join", "source": "root-b", "target": "join"},
            {"id": "a-join", "source": "root-a", "target": "join"},
        ],
    }


async def database_and_dag_checks() -> None:
    builtins = agent_teams.list_builtin_teams()
    check({team["id"] for team in builtins} == {
        "builtin-software-planning", "builtin-paper-review", "builtin-knowledge-synthesis"
    }, "三支内置团队均可加载且通过 schemaVersion=1 校验")
    check(all(team["builtin"] for team in builtins), "内置团队标记为只读来源")

    team, warnings = agent_teams.validate_team(simple_team())
    check(not warnings and len(team["nodes"]) == 3, "合法多根/扇入 DAG 通过校验")
    cyclic = simple_team("循环")
    cyclic["edges"].append({"id": "cycle", "source": "join", "target": "root-a"})
    try:
        agent_teams.validate_team(cyclic)
        check(False, "循环 DAG 被拒绝")
    except agent_teams.TeamValidationError:
        check(True, "循环 DAG 被拒绝")
    duplicate_edge_id = simple_team("重复边 ID")
    duplicate_edge_id["edges"][1]["id"] = duplicate_edge_id["edges"][0]["id"]
    try:
        agent_teams.validate_team(duplicate_edge_id)
        check(False, "重复边 ID 被拒绝")
    except agent_teams.TeamValidationError:
        check(True, "重复边 ID 被拒绝")
    invalid_output = simple_team("非法输出契约")
    invalid_output["nodes"][0]["output"] = "text"
    try:
        agent_teams.validate_team(invalid_output)
        check(False, "非对象节点输出契约返回校验错误")
    except agent_teams.TeamValidationError:
        check(True, "非对象节点输出契约返回校验错误")
    invalid_boolean = simple_team("布尔数值")
    invalid_boolean["maxConcurrency"] = True
    try:
        agent_teams.validate_team(invalid_boolean)
        check(False, "布尔值不能冒充并发数")
    except agent_teams.TeamValidationError:
        check(True, "布尔值不能冒充并发数")
    try:
        await agent_teams.resolve_input_context(["papers"], "space-a")  # type: ignore[arg-type]
        check(False, "非对象运行上下文被拒绝")
    except agent_teams.TeamValidationError:
        check(True, "非对象运行上下文被拒绝")
    try:
        agent_teams.validate_role_template({
            "name": "JSON role", "systemPrompt": "return JSON", "allowedTools": [],
            "output": {"type": "json_schema", "schema": {"type": "not-a-real-type"}},
        })
        check(False, "角色模板的非法 JSON Schema 被拒绝")
    except agent_teams.TeamValidationError:
        check(True, "角色模板的非法 JSON Schema 被拒绝")

    created = await database.create_agent_team(team, "space-a")
    check(created["name"] == "测试团队", "用户团队可创建")
    check(await database.get_agent_team(created["id"], "space-b") is None, "团队按 space-key 隔离")
    clone = await agent_teams.clone_team(created, "space-a")
    check(clone["id"] != created["id"] and "副本" in clone["name"], "克隆生成新 ID 并处理名称冲突")
    await database.update_agent_team(created["id"], {**team, "name": "已修改"}, "space-a")
    check((await database.get_agent_team(created["id"], "space-a"))["name"] == "已修改", "用户团队可更新")

    await database.insert_paper({
        "id": "paper-a", "title": "A paper", "authors": ["A"], "abstract": "secret A",
        "arxivId": "2608.00001", "pdfUrl": "https://example.invalid/a.pdf", "categories": [],
        "publishedDate": "2026-08-01",
    }, "space-a")
    stored_paper = (await database.get_all_papers("space-a"))[0]
    context = await agent_teams.resolve_input_context(
        {"kind": "papers", "entityIds": [stored_paper["id"]], "variables": {}}, "space-a")
    check(context["entities"][0]["abstract"] == "secret A", "论文 context 正文由后端按 ID 解析")
    try:
        await agent_teams.resolve_input_context(
            {"kind": "papers", "entityIds": [stored_paper["id"]], "variables": {}}, "space-b")
        check(False, "跨空间论文不能进入提示词")
    except agent_teams.TeamValidationError:
        check(True, "跨空间论文不能进入提示词")

    snapshot = copy.deepcopy(team)
    snapshot["id"] = created["id"]
    run_id = str(uuid.uuid4())
    await database.create_agent_run(
        run_id, "space-a", None, "goal", team_id=created["id"], team_name=team["name"],
        team_snapshot=snapshot, input_context={"kind": "generic", "entities": [], "variables": {}})
    await database.create_agent_run_nodes(run_id, "space-a", team["nodes"])
    await database.delete_agent_team(created["id"], "space-a")
    historical = await database.get_agent_run(run_id, "space-a")
    check(historical["teamSnapshot"]["nodes"][0]["name"] == "A", "团队删除后运行快照仍可读")

    original_run_node = agent_service.run_node
    lock = threading.Lock()
    active = 0
    max_active = 0
    join_input = ""

    def fake_run_node(spec, input_text, space_id=None, approval_mode="manual"):
        nonlocal active, max_active, join_input
        yield {"type": "start", "agent": spec["id"], "message": "start"}
        if spec["id"].startswith("root"):
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.16)
            with lock:
                active -= 1
        else:
            join_input = input_text
        yield {"type": "complete", "agent": spec["id"],
               "result": {"success": True, "raw_output": spec["name"], "structured": None}}

    agent_service.run_node = fake_run_node
    try:
        agent_runner.RUN_CANCEL[run_id] = threading.Event()
        await agent_runner._execute_dag(  # type: ignore[attr-defined]
            run_id, "space-a", "goal", snapshot,
            {"kind": "generic", "entityIds": [], "variables": {}, "entities": []})
    finally:
        agent_service.run_node = original_run_node
        agent_runner.RUN_CANCEL.pop(run_id, None)
    completed = await database.get_agent_run(run_id, "space-a")
    check(max_active == 2, "多根节点在 maxConcurrency=2 下真实并行")
    check(join_input.index("B [root-b]") < join_input.index("A [root-a]"), "扇入上下文严格遵循 edges 数组顺序")
    check(completed["status"] == "completed" and set(completed["resultSummary"]) == {"root-a", "root-b", "join"},
          "DAG 节点结果按 node ID 持久化并完成主输出")

    failure_team = simple_team("失败停止")
    failure_team["nodes"].insert(2, {
        "id": "root-c", "name": "C", "description": "C", "systemPrompt": "C",
        "allowedTools": [], "model": None, "temperature": 0.2, "maxTokens": 200,
        "output": {"type": "text"}, "position": {"x": 0, "y": 200},
    })
    failure_team["edges"].append({"id": "c-join", "source": "root-c", "target": "join"})
    failed_run_id = str(uuid.uuid4())
    await database.create_agent_run(
        failed_run_id, "space-a", None, "goal", team_id="failure-team",
        team_name=failure_team["name"], team_snapshot=failure_team,
        input_context={"kind": "generic", "entities": [], "variables": {}})
    await database.create_agent_run_nodes(failed_run_id, "space-a", failure_team["nodes"])
    started: list[str] = []

    def failing_run_node(spec, input_text, space_id=None, approval_mode="manual"):
        started.append(spec["id"])
        yield {"type": "start", "agent": spec["id"], "message": "start"}
        if spec["id"] == "root-a":
            yield {"type": "error", "agent": spec["id"], "message": "expected failure"}
        else:
            yield {"type": "complete", "agent": spec["id"],
                   "result": {"success": True, "raw_output": spec["name"], "structured": None}}

    agent_service.run_node = failing_run_node
    try:
        agent_runner.RUN_CANCEL[failed_run_id] = threading.Event()
        await agent_runner._execute_dag(  # type: ignore[attr-defined]
            failed_run_id, "space-a", "goal", failure_team,
            {"kind": "generic", "entityIds": [], "variables": {}, "entities": []})
    finally:
        agent_service.run_node = original_run_node
        agent_runner.RUN_CANCEL.pop(failed_run_id, None)
    failed_run = await database.get_agent_run(failed_run_id, "space-a")
    failed_nodes = {node["nodeId"]: node for node in
                    await database.list_agent_run_nodes(failed_run_id, "space-a")}
    check(failed_run["status"] == "failed" and failed_nodes["join"]["status"] == "skipped",
          "节点失败会使主要输出失败并跳过后代")
    check("root-b" in failed_run["resultSummary"] and "root-c" not in started
          and failed_nodes["root-c"]["status"] == "skipped",
          "保留已完成独立分支，并停止尚未开始且已无效的分支")

    terminal_race_id = str(uuid.uuid4())
    await database.create_agent_run(terminal_race_id, "space-a", None, "race")
    cancelled = await database.cancel_agent_run(terminal_race_id, "space-a")
    late_finish = await database.finish_agent_run(
        terminal_race_id, "space-a", "completed", {"type": "run_complete"}, {})
    race_events = await database.get_agent_run_events(terminal_race_id, "space-a")
    check(cancelled and not late_finish
          and await database.get_agent_run_status(terminal_race_id, "space-a") == "cancelled"
          and [event["type"] for event in race_events] == ["run_cancelled"],
          "取消终态与事件原子写入，迟到结果不能把运行复活")

    await database.create_agent_tool_approval(
        "approval-node", run_id, "space-a", "create_note", {}, node_id="root-a")
    approval = await database.get_agent_tool_approval("approval-node", run_id, "space-a")
    check(approval["nodeId"] == "root-a", "并行审批记录保留 node_id")

    # init_db is deliberately called again to cover idempotent migrations.
    await database.init_db()
    check(len(await database.list_agent_run_nodes(run_id, "space-a")) == 3, "重复初始化不破坏运行节点")


def structured_output_repair_check() -> None:
    original_client = agent_service.llm_client

    class FakeClient:
        def __init__(self): self.calls = 0
        def call_llm(self, messages, **kwargs):
            self.calls += 1
            return "not json" if self.calls == 1 else '{"answer":"repaired"}'

    client = FakeClient()
    agent_service.llm_client = client
    spec = {
        "id": "json", "name": "JSON", "systemPrompt": "json", "allowedTools": [],
        "model": None, "temperature": 0.2, "maxTokens": 200,
        "output": {"type": "json_schema", "schema": {
            "type": "object", "required": ["answer"],
            "properties": {"answer": {"type": "string"}}, "additionalProperties": False}},
    }
    try:
        events = list(agent_service.run_node(spec, "goal", "space-a"))
    finally:
        agent_service.llm_client = original_client
    complete = next(event for event in events if event["type"] == "complete")
    check(client.calls == 2 and complete["result"]["structured"] == {"answer": "repaired"},
          "JSON Schema 首次失败后只做一次无工具修复并通过校验")


def api_checks() -> None:
    original_spawn = agent_runner._spawn  # type: ignore[attr-defined]
    agent_runner._spawn = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    try:
        with TestClient(app) as client:
            a = {"X-Space-Key": "space-a"}
            b = {"X-Space-Key": "space-b"}
            listing = client.get("/api/agent/teams", headers=a)
            check(listing.status_code == 200 and len(listing.json()["teams"]) >= 3, "团队列表 API 包含内置项")
            deep_link = client.get("/teams")
            unknown_api = client.get("/api/this-route-does-not-exist", headers=a)
            check(deep_link.status_code == 200 and "text/html" in deep_link.headers.get("content-type", ""),
                  "生产静态托管支持 /teams 前端深链")
            check(unknown_api.status_code == 404 and "text/html" not in unknown_api.headers.get("content-type", ""),
                  "SPA fallback 不吞掉未知 API 的 404")
            readonly = client.delete("/api/agent/teams/builtin-paper-review", headers=a)
            check(readonly.status_code == 403, "内置团队 API 禁止删除")
            invalid_team = simple_team("invalid API team")
            invalid_team["nodes"][0]["output"] = "text"
            check(client.post("/api/agent/teams", headers=a, json=invalid_team).status_code == 400,
                  "非法团队输入返回 400 而不是 500")
            created = client.post("/api/agent/teams", headers=a, json=simple_team("API team"))
            check(created.status_code == 200, "团队 CRUD API 可创建")
            team_id = created.json()["team"]["id"]
            check(client.get(f"/api/agent/teams/{team_id}", headers=b).status_code == 404,
                  "团队 API 跨空间不可见")
            exported = client.get(f"/api/agent/teams/{team_id}/export", headers=a)
            imported = client.post("/api/agent/teams/import", headers=a, json=exported.json())
            check(imported.status_code == 200 and "副本" in imported.json()["team"]["name"],
                  "JSON 导出/导入不含历史且名称冲突自动追加副本")
            role_payload = {
                "name": "API role", "description": "role CRUD", "systemPrompt": "be precise",
                "allowedTools": [], "model": None, "temperature": 0.2, "maxTokens": 300,
                "output": {"type": "text"},
            }
            role_created = client.post("/api/agent/role-templates", headers=a, json=role_payload)
            role_id = role_created.json().get("roleTemplate", {}).get("id")
            role_updated = client.put(
                f"/api/agent/role-templates/{role_id}", headers=a,
                json={**role_payload, "name": "API role updated"})
            role_deleted = client.delete(f"/api/agent/role-templates/{role_id}", headers=a)
            check(role_created.status_code == 200 and role_updated.status_code == 200
                  and role_updated.json()["roleTemplate"]["name"] == "API role updated"
                  and role_deleted.status_code == 200,
                  "用户角色模板 API 支持创建、更新和删除")
            check(client.put("/api/agent/role-templates/builtin-role-analyst", headers=a,
                             json=role_payload).status_code == 403,
                  "内置角色模板 API 保持只读")
            legacy = client.post("/api/agent/runs", headers=a, json={"requirement": "legacy", "roles": ["architect"]})
            team_run = client.post("/api/agent/runs", headers=a, json={
                "teamId": "builtin-paper-review", "requirement": "review",
                "context": {"kind": "papers", "entityIds": [], "variables": {}}})
            check(legacy.status_code == 200, "旧 roles 运行请求保持兼容")
            check(team_run.status_code == 200, "teamId 优先的新运行请求可提交")
            check(client.get("/api/agent/tools", headers=a).json()["tools"][0].get("policy") is not None,
                  "工具目录 API 返回来源与安全策略")
    finally:
        agent_runner._spawn = original_spawn  # type: ignore[attr-defined]


async def main() -> int:
    temp_dir = Path(tempfile.mkdtemp(prefix="qa_agent_teams_"))
    database.DB_PATH = temp_dir / "ai_research_os.db"
    await database.init_db()
    await database_and_dag_checks()
    structured_output_repair_check()
    api_checks()
    print(f"\nAgent teams QA: {PASSED}/{PASSED + FAILED} passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
