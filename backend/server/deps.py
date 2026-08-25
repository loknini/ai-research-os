"""FastAPI dependencies for space-key soft isolation.

A request's ``space_id`` is derived from the ``X-Space-Key`` header:

* ``normalize_space_key`` trims and lower-cases the raw key (no hashing — the
  key *is* the anonymous identity dimension).
* ``get_space_id`` is injected at the **handler** level on every data route so
  the resolved value can be passed straight through to the DB layer.

System routes (``settings`` / ``healthz`` / ``backup``) deliberately do NOT use
this dependency — they are global configuration / liveness / global-backup
endpoints and remain exempt from isolation.
"""
from __future__ import annotations

from fastapi import Header, HTTPException

# 暴露给本模块与调用方复用，保持与 scripts/database.py 默认空间一致。
DEFAULT_SPACE = "__default__"

# space key 归一后的最小长度（允许中文 / 字母 / 数字 / 常见符号）。
MIN_KEY_LEN = 4


def normalize_space_key(raw: str) -> str:
    """Trim + lower-case normalization; no hashing (soft isolation).

    Args:
        raw: The raw ``X-Space-Key`` header value.

    Returns:
        The normalized space key, or ``""`` when the input is missing.
    """
    return (raw or "").strip().lower()


async def get_space_id(x_space_key: str = Header(default=None, alias="X-Space-Key")) -> str:
    """Resolve ``space_id`` from the ``X-Space-Key`` request header.

    * Missing / empty header      -> HTTP 400 (``MISSING_SPACE_KEY``)
    * Normalized length < 4       -> HTTP 400 (``INVALID_SPACE_KEY``)

    Returns:
        The normalized ``space_id``. A value exactly equal to ``__default__``
        resolves to the legacy / shared space.
    """
    if not x_space_key or not x_space_key.strip():
        raise HTTPException(status_code=400, detail="Missing X-Space-Key header")
    key = normalize_space_key(x_space_key)
    if len(key) < MIN_KEY_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"X-Space-Key too short (min {MIN_KEY_LEN} chars after normalization)",
        )
    return key


__all__ = ["DEFAULT_SPACE", "MIN_KEY_LEN", "normalize_space_key", "get_space_id"]
