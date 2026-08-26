"""Complexity comparison and affected-family derivation.

Compares the OLD vs NEW master-complexity sales codes per harness family, then
consolidates the harness families affected — by DTx change, by complexity
change, or both — with the evidence for each. DTx families that can't be
mapped to a master worksheet via the cross-reference are surfaced as
unresolved, never guessed.
"""

from __future__ import annotations

import logging

from splice.harnesscx.adapters import CrossRef, extract_family_sales_codes
from splice.harnesscx.models import AffectedFamily, ComplexityFamilyChange

logger = logging.getLogger(__name__)


def compare_complexity(
    old_master_bytes: bytes,
    new_master_bytes: bytes,
    crossref: CrossRef,
    universe: set[str],
) -> list[ComplexityFamilyChange]:
    """Per family worksheet, the sales codes added/removed between OLD and NEW master."""
    old_codes = extract_family_sales_codes(old_master_bytes, crossref.worksheets, universe)
    new_codes = extract_family_sales_codes(new_master_bytes, crossref.worksheets, universe)

    changes: list[ComplexityFamilyChange] = []
    for worksheet in sorted(set(old_codes) | set(new_codes)):
        old_set = old_codes.get(worksheet, set())
        new_set = new_codes.get(worksheet, set())
        added = sorted(new_set - old_set)
        removed = sorted(old_set - new_set)
        if added or removed:
            changes.append(ComplexityFamilyChange(
                worksheet=worksheet,
                canonical_family=crossref.worksheet_to_canonical.get(worksheet, worksheet),
                added_codes=added, removed_codes=removed,
            ))
    logger.info("Complexity compare: %d families with sales-code changes.", len(changes))
    return changes


def affected_families(
    dtx_family_counts: dict[str, int],
    complexity_changes: list[ComplexityFamilyChange],
    crossref: CrossRef,
) -> list[AffectedFamily]:
    """Consolidate affected harness families with reasons and source links.

    ``dtx_family_counts`` maps a DTx ``Harness Family`` name to its number of
    change rows (empty when no DTx change data is loaded).
    """
    by_worksheet: dict[str, AffectedFamily] = {}
    unresolved: dict[str, AffectedFamily] = {}

    for dtx_family, count in dtx_family_counts.items():
        if not dtx_family:
            continue
        worksheet = crossref.worksheet_for_dtx(dtx_family)
        if worksheet:
            canonical = crossref.worksheet_to_canonical.get(worksheet, dtx_family)
            af = by_worksheet.setdefault(
                worksheet, AffectedFamily(family=canonical, worksheet=worksheet))
            af.by_dtx = True
            af.dtx_change_count += count
        else:
            af = unresolved.setdefault(
                dtx_family, AffectedFamily(family=dtx_family, worksheet="", resolved=False))
            af.by_dtx = True
            af.dtx_change_count += count

    for change in complexity_changes:
        af = by_worksheet.setdefault(
            change.worksheet,
            AffectedFamily(family=change.canonical_family, worksheet=change.worksheet))
        af.by_complexity = True
        af.added_codes = change.added_codes
        af.removed_codes = change.removed_codes

    families = list(by_worksheet.values()) + list(unresolved.values())
    for af in families:
        if af.by_dtx:
            af.reasons.append(f"DTx changes ({af.dtx_change_count})")
        if af.by_complexity:
            parts = []
            if af.added_codes:
                parts.append("+" + ", ".join(af.added_codes))
            if af.removed_codes:
                parts.append("−" + ", ".join(af.removed_codes))
            af.reasons.append("complexity sales codes: " + "  ".join(parts))
        if not af.resolved:
            af.reasons.append("no cross-reference mapping — resolve manually")

    families.sort(key=lambda a: (not a.by_complexity, not a.by_dtx, a.family))
    return families
