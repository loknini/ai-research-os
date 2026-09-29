#!/usr/bin/env python3
"""后端结构回归：锁定公开入口、路由聚合、资源文件和依赖方向。"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "backend" / "server"

def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def source_lines(path: Path) -> int:
    """返回文件总行数，用于防止入口和薄路由再次膨胀。"""
    return len(path.read_text(encoding="utf-8").splitlines())


def main() -> int:
    main_module = importlib.import_module("backend.server.main")
    check("FastAPI 公开入口保持 backend.server.main:app", hasattr(main_module, "app"))

    from backend.server.core import config as core_config

    check("核心配置解析到真实项目根目录", core_config.PROJECT_ROOT == ROOT)
    check("脚本与默认数据目录位于项目根目录下", (
        core_config.SCRIPTS_DIR == ROOT / "scripts"
        and core_config.DEFAULT_DATA_DIR == ROOT / "data"
    ))

    routers_module = importlib.import_module("backend.server.routers")
    routers = routers_module.routers
    check("路由聚合数量保持稳定", len(routers) == 22)
    check("路由对象没有重复注册", len({id(router) for router in routers}) == len(routers))

    retired_modules = (
        "rag_service",
        "rag_runner",
        "local_embed",
        "vector_index",
        "vec_store",
        "agent_service",
        "agent_runner",
        "agent_teams",
        "development_runner",
        "development_workspace",
        "config",
        "errors",
        "logging_config",
        "admin_access",
        "instance_guard",
        "health",
    )
    check(
        "已退役的根级兼容模块全部删除",
        all(not (SERVER / f"{name}.py").exists() for name in retired_modules),
    )
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check(
        "废弃 backend/logs 且禁止旧日志目录回流",
        not (ROOT / "backend" / "logs").exists() and "/backend/logs/" in gitignore,
    )

    canonical_modules = (
        "backend.server.rag.service",
        "backend.server.rag.runner",
        "backend.server.rag.local_embed",
        "backend.server.rag.vector_index",
        "backend.server.rag.vec_store",
        "backend.server.agents.service",
        "backend.server.agents.runner",
        "backend.server.agents.teams",
        "backend.server.development.runner",
        "backend.server.development.workspace",
        "backend.server.core.config",
        "backend.server.core.errors",
        "backend.server.core.logging",
        "backend.server.core.log_maintenance",
        "backend.server.core.admin_access",
        "backend.server.core.instance_guard",
        "backend.server.core.health",
    )
    for module_name in canonical_modules:
        importlib.import_module(module_name)
    check("领域与核心模块可通过正式路径导入", True)

    domain_packages = ("core", "rag", "agents", "development", "services")
    check(
        "后端领域包结构完整",
        all((SERVER / package / "__init__.py").is_file() for package in domain_packages),
    )
    check("main.py 保持轻量装配入口", source_lines(SERVER / "main.py") <= 100)
    check(
        "备份与设置路由保持轻量",
        all(
            source_lines(SERVER / "routers" / name) <= 60
            for name in ("backup.py", "settings.py")
        ),
    )
    from backend.server import tool_registry
    from backend.server.agents import teams as agent_teams

    check("四套内置专家团队仍可加载", len(agent_teams.list_builtin_teams()) == 4)
    tool_names = {item["function"]["name"] for item in tool_registry.get_tools()}
    check("核心工具与技能仍已注册", {"create_task", "web_search"} <= tool_names)

    expected_resources = (
        ROOT / "backend" / "resources" / "agents" / "agent_roles.json",
        ROOT / "backend" / "resources" / "agents" / "agent_role_templates.json",
        ROOT / "backend" / "resources" / "agents" / "teams" / "knowledge-synthesis.json",
    )
    check("Agent 内置资源文件完整", all(path.is_file() for path in expected_resources))

    path_mutations: list[str] = []
    for path in SERVER.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "sys.path.append" in text or "sys.path.insert" in text:
            path_mutations.append(str(path.relative_to(ROOT)))
    check("后端包内不存在 sys.path 注入", not path_mutations)

    # 领域层只能依赖核心层、基础设施和其它领域服务，不能反向依赖 HTTP 路由。
    invalid_domain_imports: list[str] = []
    for package in ("rag", "agents", "development", "services", "core"):
        package_dir = SERVER / package
        if not package_dir.exists():
            continue
        for path in package_dir.rglob("*.py"):
            if any("routers" in module.split(".") for module in imported_modules(path)):
                invalid_domain_imports.append(str(path.relative_to(ROOT)))
    check("领域与核心层不反向依赖 routers", not invalid_domain_imports)

    print("BACKEND_ARCHITECTURE_QA_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
