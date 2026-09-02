#!/usr/bin/env python3
"""Generate docs/_meta.json from code facts (single source of truth)."""
import json
import re
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
db_text = (ROOT / "scripts" / "database.py").read_text(encoding="utf-8")
raw_tables = re.findall(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", db_text)
# Filter: keep only lowercase/underscore names, drop comment fragments
tables = [t for t in raw_tables if re.match(r"^[a-z_]+$", t)]
space_m = re.search(r"SPACE_TABLES\s*=\s*\[(.*?)\]", db_text, re.S)
space_tables = re.findall(r'"([^"]+)"', space_m.group(1)) if space_m else []

routers = [p.stem for p in (ROOT / "backend" / "server" / "routers").glob("*.py") if p.name != "__init__.py"]
# health router lives in backend/server/health.py
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
    "generatedFrom": ["scripts/database.py", "backend/server/routers/__init__.py", "frontend/src/App.tsx", "backend/server/main.py"],
}

out = ROOT / "docs" / "_meta.json"
out.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {out}: {json.dumps(meta, ensure_ascii=False)}")
