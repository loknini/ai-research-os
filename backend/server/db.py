"""Database bootstrap.

Makes ``scripts/database.py`` importable in-process (the ``scripts/`` directory
is already on ``sys.path`` thanks to ``backend/server/__init__.py``) and
re-exports the helpers used by the routers.

``DATA_DIR`` / ``DB_PATH`` are already exported on ``os.environ`` by
``config.py`` by the time this module is imported, so ``database`` resolves the
correct SQLite file.
"""
from __future__ import annotations

from scripts import database  # noqa: F401  (scripts.database 正规包导入)

from . import config


async def init_db() -> None:
    """Initialize the SQLite schema (idempotent; safe to call on startup)."""
    await database.init_db()


__all__ = ["database", "init_db", "config"]
