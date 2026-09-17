"""Ordered migration registry for the application schema."""
from __future__ import annotations

import aiosqlite

from .runner import Migration
from .v0001_baseline import BaselineContext
from . import v0001_baseline
from ..schema import validate_schema


def build_migrations(
    context: BaselineContext,
    *,
    baseline_retries: int = 8,
) -> tuple[Migration, ...]:
    """Return every supported migration in strict version order."""

    async def apply_baseline(_conn: aiosqlite.Connection | None) -> None:
        await v0001_baseline.upgrade(context, max_retries=baseline_retries)

    async def validate_baseline(conn: aiosqlite.Connection) -> None:
        await validate_schema(
            conn,
            space_tables=context.space_tables,
            require_foreign_keys=False,
        )

    return (
        Migration(
            version=v0001_baseline.VERSION,
            name=v0001_baseline.NAME,
            checksum=v0001_baseline.CHECKSUM,
            upgrade=apply_baseline,
            transactional=False,
            validate=validate_baseline,
        ),
    )


__all__ = ["build_migrations"]
