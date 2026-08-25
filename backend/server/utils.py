"""Small shared backend helpers (no external dependencies)."""

from __future__ import annotations


def mask_key(key: str) -> str:
    """Return a redacted representation of an API key for safe display.

    Shows the first/last 4 characters and masks the middle with 6 stars.
    Short keys (<= 8 chars) are fully masked. This is the single canonical
    implementation — previously duplicated in ``llm.py`` and ``settings.py``
    with inconsistent behaviour (see TECH-DEBT T1).
    """
    key = key or ""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * 6}{key[-4:]}"
