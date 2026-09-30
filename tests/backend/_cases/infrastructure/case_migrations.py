#!/usr/bin/env python3
"""Regression checks for the explicit SQLite schema migration runner."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from tests.backend._cases import PROJECT_ROOT
TMP = Path(tempfile.mkdtemp(prefix="qa_migrations_"))
os.environ["DATA_DIR"] = str(TMP)

from scripts import database  # noqa: E402
from scripts.db.migrations import Migration, MigrationError, run_migrations  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    await database.init_db()
    async with database.get_db() as conn:
        rows = await (
            await conn.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            )
        ).fetchall()
        pragma = await (await conn.execute("PRAGMA user_version")).fetchone()
    latest = int(rows[-1]["version"] if rows else 0)
    expected_versions = list(range(1, latest + 1))
    check(
        "fresh DB records every registered migration",
        [int(row["version"]) for row in rows] == expected_versions,
        f"versions={expected_versions}",
    )
    check("PRAGMA user_version mirrors the ledger", bool(pragma and pragma[0] == latest))

    await database.init_db()
    async with database.get_db() as conn:
        count = await (await conn.execute("SELECT COUNT(*) FROM schema_migrations")).fetchone()
    check("repeated startup is idempotent", bool(count and count[0] == latest))

    stored_name = str(rows[0]["name"])
    stored_checksum = str(rows[0]["checksum"])

    async def noop(_conn) -> None:
        return None

    recorded = tuple(
        Migration(int(row["version"]), str(row["name"]), str(row["checksum"]), noop)
        for row in rows
    )
    bad_history = (
        Migration(1, stored_name, "0" * 64, noop),
        *recorded[1:],
    )
    try:
        await run_migrations(
            get_db=database.get_db,
            data_dir=database.DATA_DIR,
            migrations=bad_history,
        )
    except MigrationError as exc:
        check("edited migration history is rejected", "differs from the applied history" in str(exc))
    else:
        check("edited migration history is rejected", False)

    async def fail_after_ddl(conn) -> None:
        assert conn is not None
        await conn.execute("CREATE TABLE migration_should_rollback (id INTEGER PRIMARY KEY)")
        raise RuntimeError("fault injection")

    baseline = Migration(1, stored_name, stored_checksum, noop)
    failing_version = latest + 1
    failing = Migration(failing_version, "fault_injection", "f" * 64, fail_after_ddl)
    try:
        await run_migrations(
            get_db=database.get_db,
            data_dir=database.DATA_DIR,
            migrations=(*recorded, failing),
        )
    except RuntimeError as exc:
        check("migration failure is propagated", str(exc) == "fault injection")
    else:
        check("migration failure is propagated", False)
    async with database.get_db() as conn:
        leaked = await (
            await conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_should_rollback'"
            )
        ).fetchone()
        failed_version = await (
            await conn.execute("SELECT 1 FROM schema_migrations WHERE version=?", (failing_version,))
        ).fetchone()
    check("failed transactional DDL is rolled back", leaked is None)
    check("failed migration does not advance the ledger", failed_version is None)

    future_version = latest + 1
    async with database.get_db() as conn:
        await conn.execute(
            "INSERT INTO schema_migrations "
            "(version, name, checksum, applied_at, duration_ms) VALUES (?, 'future', ?, 0, 0)",
            (future_version, "2" * 64),
        )
        await conn.execute(f"PRAGMA user_version = {future_version}")
    try:
        await database.init_db()
    except MigrationError as exc:
        check("newer database versions are rejected", "newer than this application" in str(exc))
    else:
        check("newer database versions are rejected", False)

    async with database.get_db() as conn:
        await conn.execute("DELETE FROM schema_migrations WHERE version = 1")
    future = Migration(future_version, "future", "2" * 64, noop)
    try:
        await run_migrations(
            get_db=database.get_db,
            data_dir=database.DATA_DIR,
            migrations=(*recorded, future),
        )
    except MigrationError as exc:
        check("migration history gaps are rejected", "history has gaps" in str(exc))
    else:
        check("migration history gaps are rejected", False)

    failed = [name for name, ok, _detail in CHECKS if not ok]
    print(f"\nMigration QA: {len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
    if failed:
        print("Failed: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
