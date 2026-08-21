"""Text normalization and field-extraction helpers shared across engines.

These were previously duplicated (with subtle divergences) in
``dtx_compare_engine`` and ``secr_enrichment_engine``. This module is the single
canonical home. The behavior here matches the former ``dtx_compare_engine``
implementations, which were selected as canonical during the Phase 2 DTCR review.
"""

from __future__ import annotations

import re

import pandas as pd
from pandas.api.types import is_scalar

__all__ = [
    "normalize_value",
    "normalize_cell",
    "normalize_match_text",
    "split_delimited_values",
    "extract_transmittal_number",
    "extract_bulletin_number",
]


def normalize_value(value: object) -> str:
    """Return a trimmed string form of ``value`` (``""`` for null/NaN).

    Integer-valued floats are rendered without a trailing ``.0`` so that Excel
    numeric cells (e.g. ``60001.0``) compare equal to their string form.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_cell(value: object) -> object:
    """Like :func:`normalize_value` but preserves non-string scalars.

    Strings are trimmed and nulls become ``""``; every other value passes
    through unchanged. Used where downstream code needs original dtypes.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if is_scalar(value) and pd.isna(value):
        return ""
    return value


def normalize_match_text(value: object) -> str:
    """Uppercase, replace non-word characters with spaces, and collapse runs.

    Used for fuzzy name matching (e.g. device name contained in a transmittal).
    """
    text = normalize_value(value)
    if not text:
        return ""
    text = re.sub(r"[^\w\s]", " ", text.upper())
    return re.sub(r"\s+", " ", text).strip()


def split_delimited_values(value: object) -> list[str]:
    """Split a cell that may hold several values joined by ``, ; | \\n``.

    Returns the non-empty, trimmed tokens in order.
    """
    tokens: list[str] = []
    for part in re.split(r"[,;|\n]+", normalize_value(value)):
        token = normalize_value(part)
        if token:
            tokens.append(token)
    return tokens


def extract_transmittal_number(value: object) -> str:
    """Return the leading run of digits from a device-transmittal string.

    ``"60001 - SWITCH LEFT"`` -> ``"60001"``; no leading digits -> ``""``.
    """
    match = re.match(r"^(\d+)", normalize_value(value))
    return match.group(1) if match else ""


def extract_bulletin_number(text: object) -> str:
    """Extract the first bulletin identifier following the word 'Bulletin'.

    Handles formats such as ``Bulletin 318898``, ``Bulletin: 318898-02``, and
    ``Bulletin_ 318898_02``. Returns ``""`` when no explicit bulletin marker is
    present -- notably, a bare token like ``"Routing"`` is NOT treated as a
    bulletin (this is the stricter, canonical behavior).
    """
    value = normalize_value(text)
    if not value:
        return ""
    match = re.search(
        r"\bbulletin(?:\b|_)[\s_:#-]*(?:no\.?[\s_:#-]*)?([A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)*)",
        value,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return ""
