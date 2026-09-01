"""Resolve DTx circuits against a harness's own complexity table.

For one harness family: group the DTx rows by circuit, union each circuit's
sales-code conditions, then evaluate that condition against every build the
harness ships as. The result says, per circuit, which part numbers carry it.

Two rules are inherited from the inline engine and matter more than anything
else here:

* **A condition is only ever evaluated against the harness that owns it.**
  Part numbers on one harness say nothing about part numbers on another.
* **A code the complexity does not track is unknown, not absent, and is
  treated as present.** Silence in a complexity header can therefore widen a
  circuit's applicability but can never manufacture a missing one. Where that
  happens the codes are reported on the finding, because a wide answer built
  on silence is worth knowing about.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

from splice.dtxcircuits.models import (
    ALL_BUILDS,
    CnumApplicability,
    CodeGap,
    NEVER,
    NO_COMPLEXITY,
    UNCONDITIONAL,
    VARIANT,
    CircuitApplicability,
    CircuitRow,
    HarnessAnalysis,
)
from splice.dtxcircuits import conventions
from splice.inline import salescode
from splice.inline.complexity import applies_in
from splice.inline.model import Harness

logger = logging.getLogger(__name__)


def union_condition(rows: Iterable[CircuitRow]) -> Optional[str]:
    """One condition covering every occurrence of a circuit on a harness.

    A circuit reaching the same harness through several pins is carried when
    ANY of those occurrences applies, so the conditions are OR-ed. A single
    unconditional occurrence makes the whole circuit unconditional — returned
    as ``None``, which no expression can express.
    """
    parts: List[str] = []
    for row in rows:
        # a bare universal code means the same as a blank cell
        condition = conventions.effective_condition(row.sales_code)
        if not condition:
            return None
        parts.append(f"({condition})")
    if not parts:
        return None
    return "/".join(sorted(set(parts)))


def _resolve(condition: Optional[str], harness: Optional[Harness]):
    """Classify one condition against a harness's builds.

    Returns ``(classification, builds_with, builds_without, untracked)``.
    """
    if harness is None or not harness.builds:
        return NO_COMPLEXITY, [], [], []

    untracked = [] if condition is None else sorted(
        code for code in salescode.codes_in(condition)
        if code not in harness.complexity_codes)

    if condition is None:
        return UNCONDITIONAL, [b.part_number for b in harness.builds], [], untracked

    with_it, without = [], []
    for build in harness.builds:
        # unknown-as-present lives in applies_in; see module docstring
        if applies_in(condition, build.codes, harness.complexity_codes):
            with_it.append(build.part_number)
        else:
            without.append(build.part_number)
    if not with_it:
        return NEVER, with_it, without, untracked
    if not without:
        return ALL_BUILDS, with_it, without, untracked
    return VARIANT, with_it, without, untracked


def analyze_cnums(rows: Iterable[CircuitRow],
                  harness: Optional[Harness],
                  harness_name: str = "") -> List[CnumApplicability]:
    """Resolve every connector (CNUM) the DTx puts on one harness family."""
    by_cnum: Dict[str, List[CircuitRow]] = {}
    for row in rows:
        if row.cnum:
            by_cnum.setdefault(row.cnum, []).append(row)

    out: List[CnumApplicability] = []
    for cnum in sorted(by_cnum):
        occurrences = by_cnum[cnum]
        condition = union_condition(occurrences)
        classification, with_it, without, untracked = _resolve(condition, harness)
        out.append(CnumApplicability(
            harness=harness_name, cnum=cnum, classification=classification,
            expression=condition,
            connector_pn=next((o.connector_pn for o in occurrences
                               if o.connector_pn), ""),
            circuits=sorted({o.circuit for o in occurrences}),
            builds_with=with_it, builds_without=without,
            untracked_codes=untracked,
            pins=sorted({o.pin for o in occurrences if o.pin})))
    return out


def code_gaps(rows: Iterable[CircuitRow],
              harness: Optional[Harness]) -> List[CodeGap]:
    """Sales codes the DTx uses for this family that its complexity omits.

    Reported with everything that depends on them, because each one makes the
    circuits resting on it read wider than the data can justify.
    """
    if harness is None:
        return []
    gaps: Dict[str, CodeGap] = {}
    for row in rows:
        # a bare universal code is not a gap: no complexity file lists it, and
        # reporting it gives the customer nothing they can act on
        condition = conventions.effective_condition(row.sales_code)
        if not condition:
            continue
        for code in salescode.codes_in(condition):
            if code in harness.complexity_codes:
                continue
            gap = gaps.setdefault(code, CodeGap(code=code))
            gap.occurrences += 1
            if row.circuit not in gap.circuits:
                gap.circuits.append(row.circuit)
            if row.cnum and row.cnum not in gap.cnums:
                gap.cnums.append(row.cnum)
    for gap in gaps.values():
        gap.circuits.sort()
        gap.cnums.sort()
    return [gaps[c] for c in sorted(gaps)]


def unused_codes(rows: Iterable[CircuitRow],
                 harness: Optional[Harness]) -> List[str]:
    """Codes the complexity tracks that no circuit on this family conditions on."""
    if harness is None:
        return []
    used: set = set()
    for row in rows:
        condition = (row.sales_code or "").strip()
        if condition:
            used.update(salescode.codes_in(condition))
    return sorted(harness.complexity_codes - used)


def analyze_harness(rows: Iterable[CircuitRow],
                    harness: Optional[Harness],
                    harness_name: str = "") -> HarnessAnalysis:
    """Resolve every circuit the DTx puts on one harness family."""
    rows = list(rows)
    name = harness_name or (harness.name if harness else "")
    analysis = HarnessAnalysis(
        harness=name,
        def_id=harness.def_id if harness else "",
        builds=len(harness.builds) if harness else 0,
    )

    by_circuit: Dict[str, List[CircuitRow]] = {}
    for row in rows:
        by_circuit.setdefault(row.circuit, []).append(row)

    for circuit in sorted(by_circuit):
        occurrences = by_circuit[circuit]
        condition = union_condition(occurrences)
        raw = sorted({o.sales_code.strip() for o in occurrences if o.sales_code.strip()})
        pins = sorted({f"{o.cnum}/{o.pin}".strip("/") for o in occurrences if o.cnum or o.pin})

        classification, with_it, without, untracked = _resolve(condition, harness)
        if classification == NO_COMPLEXITY and condition is not None \
                and harness is not None:
            untracked = sorted(code for code in salescode.codes_in(condition)
                               if code not in harness.complexity_codes)

        analysis.circuits.append(CircuitApplicability(
            harness=name, circuit=circuit, classification=classification,
            expression=condition, raw_expressions=raw,
            builds_with=with_it, builds_without=without,
            untracked_codes=untracked, pins=pins))

    analysis.cnums = analyze_cnums(rows, harness, harness_name=name)
    analysis.code_gaps = code_gaps(rows, harness)
    analysis.unused_codes = unused_codes(rows, harness)
    logger.info("Harness %s: %d circuits, %d connectors -> %s", name,
                len(analysis.circuits), len(analysis.cnums), analysis.counts)
    return analysis


def analyze(rows: Iterable[CircuitRow],
            harnesses: Dict[str, Harness],
            match=None) -> List[HarnessAnalysis]:
    """Analyze every harness family present in the DTx rows.

    ``harnesses`` maps a DTx family name to its :class:`Harness`. ``match`` is
    an optional ``(family) -> Harness | None`` resolver for programmes whose
    complexity files are named differently from the DTx families; without it
    the mapping must be exact, because guessing which complexity file belongs
    to which family is how the wrong applicability gets attributed.
    """
    by_family: Dict[str, List[CircuitRow]] = {}
    for row in rows:
        by_family.setdefault(row.harness_family, []).append(row)

    out: List[HarnessAnalysis] = []
    for family in sorted(by_family):
        harness = match(family) if match else harnesses.get(family)
        out.append(analyze_harness(by_family[family], harness, harness_name=family))
    return out
