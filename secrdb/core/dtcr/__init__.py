"""DTCR loading and matching — the single source of truth.

DTCR-to-harness-family matching previously lived in two engines with divergent
behavior. This package consolidates them. The canonical behavior (selected in
the Phase 2 review) is the former ``dtx_compare_engine`` implementation:

* delimited Device Control Number cells are split and indexed,
* all matching harness families are aggregated (comma-joined),
* bulletin extraction is strict (see :func:`secrdb.core.common.text.extract_bulletin_number`).
"""

from __future__ import annotations

from secrdb.core.dtcr.matching import (
    DTCR_MATCHING_COLUMNS,
    match_dtcr_to_harness_family,
    prepare_dtcr_for_matching,
)

__all__ = [
    "DTCR_MATCHING_COLUMNS",
    "match_dtcr_to_harness_family",
    "prepare_dtcr_for_matching",
]
