"""Canonical schema invariants used after migrations."""
from __future__ import annotations

from collections.abc import Sequence

import aiosqlite

REQUIRED_TABLES = frozenset(
    {
        "papers",
        "cron_jobs",
        "cron_run_history",
        "software_projects",
        "tasks",
        "code_generations",
        "notes",
        "note_links",
        "experiments",
        "experiment_runs",
        "version_history",
        "conversations",
        "chat_messages",
        "agent_sessions",
        "agent_messages",
        "agent_generated_files",
        "agent_runs",
        "development_run_steps",
        "development_artifacts",
        "agent_teams",
        "agent_role_templates",
        "agent_run_nodes",
        "agent_run_events",
        "agent_tool_approvals",
        "agent_replay_messages",
        "formula_history",
        "obsidian_vaults",
        "obsidian_files",
        "rag_sources",
        "rag_documents",
        "rag_chunks",
        "rag_embedding_profiles",
        "rag_index_jobs",
        "rag_worker_lease",
        "rag_vec_meta",
        "global_config",
        "schema_migrations",
    }
)

REQUIRED_COLUMNS = {
    "papers": {"space_id", "arxiv_id", "bibtex"},
    "cron_jobs": {"space_id", "job_type", "payload"},
    "conversations": {"space_id", "current_leaf_id", "metadata"},
    "chat_messages": {"space_id", "parent_id"},
    "agent_runs": {"space_id", "team_id", "run_kind", "lease_owner"},
    "rag_sources": {
        "space_id",
        "embedding_provider",
        "embedding_profile_id",
        "active_generation_id",
    },
    "rag_documents": {"space_id", "content_hash", "generation_id"},
    "rag_chunks": {"space_id", "embedding_profile_id", "generation_id"},
    "rag_index_jobs": {"space_id", "dedupe_key"},
    "rag_vec_meta": {"space_id", "profile_id", "ready"},
}


class SchemaValidationError(RuntimeError):
    """The database does not satisfy the schema contract for this build."""


async def validate_schema(
    conn: aiosqlite.Connection,
    *,
    space_tables: Sequence[str],
    require_foreign_keys: bool = True,
    check_integrity: bool = True,
) -> None:
    """Validate structural, integrity and isolation invariants."""
    table_rows = await (
        await conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    ).fetchall()
    tables = {str(row["name"]) for row in table_rows}
    missing_tables = sorted(REQUIRED_TABLES - tables)
    if missing_tables:
        raise SchemaValidationError(f"missing required tables: {missing_tables}")

    for table, required in REQUIRED_COLUMNS.items():
        rows = await (await conn.execute(f'PRAGMA table_info("{table}")')).fetchall()
        columns = {str(row["name"]) for row in rows}
        missing = sorted(required - columns)
        if missing:
            raise SchemaValidationError(f"table {table} is missing columns: {missing}")

    for table in space_tables:
        rows = await (await conn.execute(f'PRAGMA table_info("{table}")')).fetchall()
        if "space_id" not in {str(row["name"]) for row in rows}:
            raise SchemaValidationError(f"table {table} is missing space_id")

    if check_integrity:
        integrity = await (await conn.execute("PRAGMA integrity_check")).fetchone()
        if not integrity or str(integrity[0]).lower() != "ok":
            raise SchemaValidationError(f"integrity_check failed: {tuple(integrity or ())!r}")

    if require_foreign_keys:
        violations = await (await conn.execute("PRAGMA foreign_key_check")).fetchall()
        if violations:
            sample = [tuple(row) for row in violations[:10]]
            raise SchemaValidationError(f"foreign_key_check failed: {sample!r}")


__all__ = [
    "REQUIRED_COLUMNS",
    "REQUIRED_TABLES",
    "SchemaValidationError",
    "validate_schema",
]
