"""Small, dependency-free SQLite migration runner.

SQLite is the only supported database, so pulling in an ORM solely for schema
versioning would conflict with the project's small-dependency constraint.  The
runner provides the pieces this application needs: an immutable migration
ledger, checksum validation, transactional upgrades and cross-process startup
serialization.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Sequence

import aiosqlite

from scripts.process_utils import pid_is_running

ConnectionFactory = Callable[..., object]
Upgrade = Callable[[aiosqlite.Connection | None], Awaitable[None]]
Validate = Callable[[aiosqlite.Connection], Awaitable[None]]

LEDGER_TABLE = "schema_migrations"
LOCK_NAME = ".airos-schema-migration.lock"
LOCK_STALE_SECONDS = 30 * 60
LOCK_WAIT_SECONDS = 180


class MigrationError(RuntimeError):
    """Raised when the on-disk schema cannot be upgraded safely."""


def migration_checksum(version: int, name: str, revision: str) -> str:
    """Return a stable checksum for an immutable logical migration revision."""
    value = f"{version}:{name}:{revision}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def migration_file_checksum(path: str | Path) -> str:
    """Hash a migration file with newline normalization.

    The assignment line itself is excluded to avoid a self-referential hash.
    Applied files are immutable: changing any other line produces a startup
    mismatch against the ledger.
    """
    source = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")
    payload = "\n".join(
        line for line in source.split("\n") if not line.startswith("CHECKSUM = ")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    checksum: str
    upgrade: Upgrade
    transactional: bool = True
    validate: Validate | None = None


@dataclass(frozen=True, slots=True)
class _LockLease:
    path: Path
    token: str


_pid_is_alive = pid_is_running


def _read_lock_owner(lock_path: Path) -> tuple[int, float, str]:
    try:
        raw = lock_path.read_text(encoding="ascii", errors="ignore")
        fields = dict(part.split("=", 1) for part in raw.split() if "=" in part)
        return (
            int(fields.get("pid", "0")),
            float(fields.get("time", "0")),
            fields.get("token", ""),
        )
    except (OSError, ValueError):
        return 0, 0.0, ""


async def _acquire_lock(data_dir: Path) -> _LockLease:
    """Wait for and acquire the startup migration lock."""
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / LOCK_NAME
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        token = uuid.uuid4().hex
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(
                    fd,
                    f"pid={os.getpid()} time={time.time()} token={token}\n".encode("ascii"),
                )
            finally:
                os.close(fd)
            return _LockLease(lock_path, token)
        except FileExistsError as exc:
            owner_pid, created_at, _owner_token = _read_lock_owner(lock_path)
            stale = bool(created_at and time.time() - created_at > LOCK_STALE_SECONDS)
            if stale or not _pid_is_alive(owner_pid):
                try:
                    lock_path.unlink()
                    continue
                except OSError:
                    pass
            if time.monotonic() >= deadline:
                raise MigrationError(
                    f"timed out waiting for schema migration lock owned by pid {owner_pid or 'unknown'}"
                ) from exc
            await asyncio.sleep(0.2)


async def _release_lock(lease: _LockLease | None) -> None:
    if lease is None:
        return
    # Windows may briefly deny deletion while another worker reads the lock.
    # Retry, and never unlink a lease that has already been replaced.
    for _attempt in range(40):
        try:
            _pid, _created_at, token = _read_lock_owner(lease.path)
            if not token:
                await asyncio.sleep(0.025)
                continue
            if token and token != lease.token:
                return
            lease.path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            await asyncio.sleep(0.025)
    raise MigrationError(f"could not release schema migration lock: {lease.path}")


async def _ensure_ledger(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at INTEGER NOT NULL,
            duration_ms INTEGER NOT NULL
        )
        """
    )


async def _applied(conn: aiosqlite.Connection) -> dict[int, tuple[str, str]]:
    await _ensure_ledger(conn)
    rows = await (
        await conn.execute(
            f"SELECT version, name, checksum FROM {LEDGER_TABLE} ORDER BY version"
        )
    ).fetchall()
    return {int(row["version"]): (str(row["name"]), str(row["checksum"])) for row in rows}


def _validate_registry(migrations: Sequence[Migration]) -> None:
    versions = [migration.version for migration in migrations]
    if not migrations or versions != list(range(1, len(migrations) + 1)):
        raise MigrationError(
            f"migration versions must be contiguous starting at 1; got {versions}"
        )
    if len(set(versions)) != len(versions):
        raise MigrationError("duplicate migration version")


async def get_schema_version(get_db: ConnectionFactory) -> int:
    """Return the latest recorded schema version, or zero for an unversioned DB."""
    async with get_db(busy_timeout_ms=30000) as conn:
        await _ensure_ledger(conn)
        row = await (
            await conn.execute(f"SELECT COALESCE(MAX(version), 0) AS version FROM {LEDGER_TABLE}")
        ).fetchone()
        return int(row["version"] if row else 0)


async def run_migrations(
    *,
    get_db: ConnectionFactory,
    data_dir: Path,
    migrations: Sequence[Migration],
    final_validate: Validate | None = None,
) -> int:
    """Apply pending migrations and return the resulting schema version.

    Normal migrations run in one ``BEGIN IMMEDIATE`` transaction together with
    their ledger insert.  Version 1 may be marked non-transactional because the
    legacy convergence code has a table rebuild that must toggle
    ``PRAGMA foreign_keys`` outside a transaction; it is deliberately
    idempotent and is recorded only after validation succeeds.
    """
    ordered = tuple(sorted(migrations, key=lambda item: item.version))
    _validate_registry(ordered)
    lock_lease: _LockLease | None = None
    try:
        lock_lease = await _acquire_lock(Path(data_dir))
        async with get_db(busy_timeout_ms=30000) as conn:
            applied = await _applied(conn)

        latest_supported = ordered[-1].version
        applied_versions = sorted(applied)
        expected_applied = list(range(1, max(applied_versions, default=0) + 1))
        if applied_versions != expected_applied:
            raise MigrationError(
                f"database migration history has gaps; got {applied_versions}, "
                f"expected {expected_applied}"
            )
        unknown = sorted(version for version in applied if version > latest_supported)
        if unknown:
            raise MigrationError(
                f"database schema v{unknown[-1]} is newer than this application supports "
                f"(latest v{latest_supported})"
            )

        by_version = {migration.version: migration for migration in ordered}
        for version, (stored_name, stored_checksum) in applied.items():
            migration = by_version.get(version)
            if migration is None:
                raise MigrationError(f"database contains unknown migration v{version}")
            if stored_name != migration.name or stored_checksum != migration.checksum:
                raise MigrationError(
                    f"migration v{version} differs from the applied history; "
                    "restore the original migration file instead of editing history"
                )

        for migration in ordered:
            if migration.version in applied:
                continue
            started = time.monotonic()
            print(f"[db] applying migration v{migration.version}: {migration.name}")
            if migration.transactional:
                async with get_db(busy_timeout_ms=30000) as conn:
                    await conn.execute("BEGIN IMMEDIATE")
                    await migration.upgrade(conn)
                    if migration.validate is not None:
                        await migration.validate(conn)
                    duration_ms = int((time.monotonic() - started) * 1000)
                    await conn.execute(
                        f"INSERT INTO {LEDGER_TABLE} "
                        "(version, name, checksum, applied_at, duration_ms) VALUES (?, ?, ?, ?, ?)",
                        (
                            migration.version,
                            migration.name,
                            migration.checksum,
                            int(time.time() * 1000),
                            duration_ms,
                        ),
                    )
                    await conn.execute(f"PRAGMA user_version = {migration.version}")
            else:
                await migration.upgrade(None)
                async with get_db(busy_timeout_ms=30000) as conn:
                    await conn.execute("BEGIN IMMEDIATE")
                    if migration.validate is not None:
                        await migration.validate(conn)
                    duration_ms = int((time.monotonic() - started) * 1000)
                    await conn.execute(
                        f"INSERT INTO {LEDGER_TABLE} "
                        "(version, name, checksum, applied_at, duration_ms) VALUES (?, ?, ?, ?, ?)",
                        (
                            migration.version,
                            migration.name,
                            migration.checksum,
                            int(time.time() * 1000),
                            duration_ms,
                        ),
                    )
                    await conn.execute(f"PRAGMA user_version = {migration.version}")
            print(f"[db] applied migration v{migration.version} in {duration_ms} ms")

        async with get_db(busy_timeout_ms=30000) as conn:
            applied = await _applied(conn)
            current = max(applied, default=0)
            if final_validate is not None:
                await final_validate(conn)
            pragma_row = await (await conn.execute("PRAGMA user_version")).fetchone()
            pragma_version = int(pragma_row[0] if pragma_row else 0)
            if pragma_version != current:
                await conn.execute(f"PRAGMA user_version = {current}")
        return current
    finally:
        await _release_lock(lock_lease)


__all__ = [
    "LEDGER_TABLE",
    "Migration",
    "MigrationError",
    "get_schema_version",
    "migration_checksum",
    "migration_file_checksum",
    "run_migrations",
]
