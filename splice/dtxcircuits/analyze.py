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
    NEVER,
    NO_COMPLEXITY,
    UNCONDITIONAL,
    VARIANT,
    CircuitApplicability,
    CircuitRow,
    HarnessAnalysis,
)
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
        condition = (row.sales_code or "").strip()
        if not condition:
            return None
        parts.append(f"({condition})")
    if not parts:
        return None
    return "/".join(sorted(set(parts)))


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

        untracked: List[str] = []
        if condition is not None and harness is not None:
            untracked = sorted(
                code for code in salescode.codes_in(condition)
                if code not in harness.complexity_codes)

        if harness is None or not harness.builds:
            applicability = CircuitApplicability(
                harness=name, circuit=circuit, classification=NO_COMPLEXITY,
                expression=condition, raw_expressions=raw, pins=pins,
                untracked_codes=untracked)
            analysis.circuits.append(applicability)
            continue

        if condition is None:
            with_it = [b.part_number for b in harness.builds]
            without = []
            classification = UNCONDITIONAL
        else:
            with_it, without = [], []
            for build in harness.builds:
                # unknown-as-present lives in applies_in; see module docstring
                if applies_in(condition, build.codes, harness.complexity_codes):
                    with_it.append(build.part_number)
                else:
                    without.append(build.part_number)
            if not with_it:
                classification = NEVER
            elif not without:
                classification = ALL_BUILDS
            else:
                classification = VARIANT

        analysis.circuits.append(CircuitApplicability(
            harness=name, circuit=circuit, classification=classification,
            expression=condition, raw_expressions=raw,
            builds_with=with_it, builds_without=without,
            untracked_codes=untracked, pins=pins))

    logger.info("Harness %s: %d circuits -> %s", name, len(analysis.circuits),
                analysis.counts)
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
