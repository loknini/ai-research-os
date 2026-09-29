#!/usr/bin/env python3
"""根据代码事实生成 docs/_meta.json，作为文档数字的单一事实源。"""
import json
import re
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
migrations_dir = ROOT / "scripts" / "db" / "migrations"
migration_paths = sorted(migrations_dir.glob("v[0-9][0-9][0-9][0-9]_*.py"))
core_path = ROOT / "scripts" / "db" / "core.py"
schema_text = "\n".join(path.read_text(encoding="utf-8") for path in migration_paths)
core_text = core_path.read_text(encoding="utf-8")
raw_tables = re.findall(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", schema_text)
# 只保留小写字母与下划线组成的表名，排除注释片段。
tables = [t for t in raw_tables if re.match(r"^[a-z_]+$", t)]
space_m = re.search(r"SPACE_TABLES\s*=\s*\[(.*?)\]", core_text, re.S)
space_tables = re.findall(r'"([^"]+)"', space_m.group(1)) if space_m else []

routers = [p.stem for p in (ROOT / "backend" / "server" / "routers").glob("*.py") if p.name != "__init__.py"]
# 健康检查路由实现在 backend/server/core/health.py。
total_routers = len(routers) + 1

app_text = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
hubs = len(re.findall(r"lazy\(", app_text))

main_text = (ROOT / "backend" / "server" / "main.py").read_text(encoding="utf-8")
version_m = re.search(r'version="([^"]+)"', main_text)
version = version_m.group(1) if version_m else "0.5.0"

meta = {
    "version": version,
    "tables": len(tables),
    "tableList": tables,
    "spaceTables": len(space_tables),
    "routers": total_routers,
    "routerList": sorted(routers + ["health"]),
    "hubs": hubs,
    "generatedFrom": [
        *[path.relative_to(ROOT).as_posix() for path in migration_paths],
        "scripts/db/core.py",
        "backend/server/routers/__init__.py",
        "frontend/src/App.tsx",
        "backend/server/main.py",
    ],
}

out = ROOT / "docs" / "_meta.json"
out.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {out}: {json.dumps(meta, ensure_ascii=False)}")
