#!/usr/bin/env python3
"""Backward-compatible public facade for the domain-oriented SQLite layer.

New persistence code belongs in ``scripts.db.core``, versioned migrations, or
one of ``scripts.db.repos``.  Existing callers may continue importing this
module while repositories are adopted incrementally.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from scripts.db import core as _core
from scripts.db.core import (
    DEFAULT_SPACE,
    PROJECT_ROOT,
    SPACE_TABLES,
    _clean_text_for_db,
    _fetchall,
    _fetchone,
    _is_locked_error,
    get_db,
    with_busy_retry,
)
from scripts.db.migrations import build_migrations, run_migrations
from scripts.db.migrations.v0001_baseline import BaselineContext
from scripts.db.schema import validate_schema

DATA_DIR = _core.DATA_DIR
DB_PATH = _core.DB_PATH


def configure_paths(
    *,
    data_dir: str | Path | None = None,
    db_path: str | Path | None = None,
) -> tuple[Path, Path]:
    """Configure storage paths for isolated tools and tests."""
    global DATA_DIR, DB_PATH
    DATA_DIR, DB_PATH = _core.configure_paths(data_dir=data_dir, db_path=db_path)
    return DATA_DIR, DB_PATH


async def _validate_baseline(conn: aiosqlite.Connection) -> None:
    await validate_schema(
        conn,
        space_tables=SPACE_TABLES,
        require_foreign_keys=False,
        check_integrity=False,
    )


async def init_db(max_retries: int = 8) -> None:
    """Migrate the database to the latest schema supported by this build."""
    context = BaselineContext(
        get_db=get_db,
        fetchall=_fetchall,
        fetchone=_fetchone,
        data_dir=DATA_DIR,
        db_path=DB_PATH,
        default_space=DEFAULT_SPACE,
        space_tables=SPACE_TABLES,
    )

    version = await run_migrations(
        get_db=get_db,
        data_dir=DATA_DIR,
        migrations=build_migrations(context, baseline_retries=max_retries),
        final_validate=_validate_baseline,
    )
    print(f"Database schema is at v{version}: {DB_PATH}")


from scripts.db.repos.papers import *
from scripts.db.repos.tasks import *
from scripts.db.repos.projects import *
from scripts.db.repos.notes import *
from scripts.db.repos.experiments import *
from scripts.db.repos.versions import *
from scripts.db.repos.chat import *
from scripts.db.repos.search import *
from scripts.db.repos.agents import *
from scripts.db.repos.cron import *
from scripts.db.repos.formula import *
from scripts.db.repos.rag import *
from scripts.db.repos.settings import *


async def _main() -> None:
    await init_db()
    old_json = DATA_DIR / "papers" / "metadata.json"
    if old_json.exists():
        print("Found existing JSON data, migrating...")
        await migrate_from_json(old_json)


if __name__ == "__main__":
    asyncio.run(_main())
