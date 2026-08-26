"""Pre-generation quality checks for a family matrix — Splice additions.

These come from field forensics in the Circuit Health work: a single truncated
part number (687894643A vs 687894643AA) flooded a health run with integrity
findings, and dead sales-code columns / unmarked parts are the upstream causes
of downstream option-window findings. Catching them BEFORE the individual file
is generated is far cheaper than dispositioning them afterwards.

Every check returns plain rows the workbench can render; none of them blocks
generation — they are advisories for the Systems Engineer.
"""

from __future__ import annotations

from splice.harnesscx.models import FamilyMatrix


def coverage_rows(matrix: FamilyMatrix) -> list[dict]:
    """Sales-code coverage: DTx usage vs complexity columns, both directions.

    A code the DTx uses but the complexity file lacks means circuits exist whose
    applicability cannot be expressed in the individual file — the classic cause
    of option-window findings later. A complexity column the DTx never uses is
    usually fine (market/phase codes) but worth a look.
    """
    dtx = set(matrix.dtx_codes)
    cx = matrix.complexity_codes
    by_code = {sc.code: sc for sc in matrix.sales_codes}
    rows: list[dict] = []
    for code in sorted(dtx | cx):
        sc = by_code.get(code)
        rows.append({
            "code": code,
            "in_dtx": code in dtx,
            "in_complexity": code in cx,
            "feature": sc.feature if sc else "",
            "origin": sc.original_expr if sc else "",
            "ok": code in cx or code not in dtx,
        })
    return rows


def pn_lookalikes(matrix: FamilyMatrix) -> list[tuple[str, str]]:
    """Part-number pairs where one is a strict prefix of the other (≤2 chars apart).

    That shape is almost always a truncated cell — the 687894643A/687894643AA
    class of defect that later floods Circuit Health with applicability
    mismatches. Surfaced here so the SE fixes the master before generating.
    """
    pns = sorted({r.current_pn for r in matrix.rows if not r.excluded and r.current_pn})
    pairs: list[tuple[str, str]] = []
    for i, a in enumerate(pns):
        for b in pns[i + 1:]:
            if b.startswith(a) and 0 < len(b) - len(a) <= 2:
                pairs.append((a, b))
    return pairs


def duplicate_pns(matrix: FamilyMatrix) -> list[str]:
    """Part numbers appearing on more than one non-excluded row."""
    seen: dict[str, int] = {}
    for r in matrix.rows:
        if not r.excluded and r.current_pn:
            seen[r.current_pn] = seen.get(r.current_pn, 0) + 1
    return sorted(pn for pn, n in seen.items() if n > 1)


def unmarked_parts(matrix: FamilyMatrix) -> list[str]:
    """Non-excluded part numbers with no X/G mark under any sales code or
    included combined expression — a part with no applicability is usually a
    missed symbol in the master."""
    included = {ce.key for ce in matrix.combined_exprs if ce.include}
    out: list[str] = []
    for r in matrix.rows:
        if r.excluded or not r.current_pn:
            continue
        has_combined = any(k in included for k in r.combined_symbols)
        if not r.symbols and not has_combined:
            out.append(r.current_pn)
    return out


def dead_code_columns(matrix: FamilyMatrix) -> list[str]:
    """Sales-code columns no non-excluded part is marked under (dead columns)."""
    marked: set[str] = set()
    for r in matrix.rows:
        if not r.excluded:
            marked.update(r.symbols)
    return sorted(sc.code for sc in matrix.sales_codes if sc.code not in marked)
