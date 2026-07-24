"""Reusable input-validation helpers for uploaded files and DataFrames.

These centralize the "check required columns / non-empty upload" patterns that
were previously copy-pasted into each loader, and raise the shared
:mod:`splice.common.errors` types so callers get uniform, actionable messages.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from splice.common.errors import SpliceInputError, SpliceSchemaError

__all__ = ["ensure_non_empty_upload", "require_columns", "missing_columns"]


def ensure_non_empty_upload(data: bytes | None, *, name: str) -> bytes:
    """Return ``data`` unchanged, or raise if it is missing/empty.

    Parameters
    ----------
    data:
        The uploaded file bytes (e.g. ``uploaded_file.getvalue()``).
    name:
        Human-readable label for the file, used in the error message.
    """
    if not data:
        raise SpliceInputError(
            f"{name} is empty or was not uploaded. Please upload a non-empty file."
        )
    return data


def missing_columns(df: pd.DataFrame, required: Sequence[str]) -> list[str]:
    """Return the subset of ``required`` columns not present in ``df``."""
    return [column for column in required if column not in df.columns]


def require_columns(df: pd.DataFrame, required: Sequence[str], *, context: str) -> None:
    """Raise :class:`SpliceSchemaError` if any ``required`` column is absent.

    The message names the missing columns and lists what was actually found, so
    the user can see how their file differs from what's expected.
    """
    missing = missing_columns(df, required)
    if missing:
        found = list(df.columns)[:20]
        raise SpliceSchemaError(
            f"{context} is missing required column(s): {missing}. "
            f"Columns found: {found}."
        )
