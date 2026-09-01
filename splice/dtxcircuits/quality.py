"""Data quality of a DTx export — the evidence for asking for a better one.

The individual complexity files are built by the Systems Engineer from
information the customer supplies, so a DTx that cannot be reconciled with
them is not two independent sources disagreeing: it is the customer's own
data disagreeing with itself. That is what makes these findings fair to send
back, and it is the framing the report is written in.

Three kinds of finding, in descending order of how hard they are to argue
with:

1. **Malformed sales-code expressions.** Unambiguous. "QB1-QA1" is false for
   every configuration, so its circuits can never be built by anyone.
2. **Never-built circuits and connectors.** A condition no build satisfies —
   either the circuit does not belong on that harness or a part number is
   missing a code it should carry.
3. **Sales codes the complexity does not track.** Stated per code and per
   harness: where it exists and where it does not, so the gap is specific
   rather than a bare count.

Counts of structure (rows, families, blanks) are reported alongside as
context. They are not presented as defects — the SE did not ask for them to
be, and a report that pads its case is easier to dismiss.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence

from splice.dtxcircuits.models import NEVER
from splice.inline import salescode

logger = logging.getLogger(__name__)

TRACKED = "tracked wherever used"
PARTIAL = "missing from some harnesses"
UNTRACKED = "not tracked anywhere"
UNASSESSED = "no complexity mapped"


@dataclass
class CodeCoverage:
    """One sales code: where the DTx uses it, and where it is known."""

    code: str
    dtx_rows: int = 0
    families: List[str] = field(default_factory=list)
    circuits: List[str] = field(default_factory=list)
    tracked_by: List[str] = field(default_factory=list)
    missing_from: List[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.tracked_by and not self.missing_from:
            return UNASSESSED
        if not self.tracked_by:
            return UNTRACKED
        return PARTIAL if self.missing_from else TRACKED

    @property
    def is_gap(self) -> bool:
        return self.status in (UNTRACKED, PARTIAL)


@dataclass
class DtxQuality:
    """Everything the dashboard and the customer-facing report need."""

    program: str = ""
    phase: str = ""
    report_date: str = ""

    # --- structure (context, not accusations) ---
    rows: int = 0
    circuits: int = 0
    connectors: int = 0
    families: int = 0
    conditioned_rows: int = 0
    unconditional_rows: int = 0
    distinct_expressions: int = 0
    distinct_codes: int = 0
    blank_circuit: int = 0
    blank_cnum: int = 0
    blank_connector_pn: int = 0

    # --- findings ---
    malformed_expressions: int = 0
    malformed_rows: int = 0
    malformed_by_kind: Dict[str, int] = field(default_factory=dict)
    repaired_expressions: int = 0

    families_mapped: int = 0
    families_unmapped: List[str] = field(default_factory=list)
    never_built_circuits: int = 0
    never_built_connectors: int = 0
    coverage: List[CodeCoverage] = field(default_factory=list)

    @property
    def conditioned_share(self) -> float:
        return (self.conditioned_rows / self.rows) if self.rows else 0.0

    @property
    def codes_not_tracked_anywhere(self) -> List[CodeCoverage]:
        return [c for c in self.coverage if c.status == UNTRACKED]

    @property
    def codes_partially_tracked(self) -> List[CodeCoverage]:
        return [c for c in self.coverage if c.status == PARTIAL]

    @property
    def finding_total(self) -> int:
        """What the customer is being asked to fix."""
        return (self.malformed_expressions + self.never_built_circuits
                + self.never_built_connectors
                + len(self.codes_not_tracked_anywhere)
                + len(self.codes_partially_tracked))

    @property
    def clean(self) -> bool:
        return self.finding_total == 0


def coverage(rows: Iterable, entries: Sequence) -> List[CodeCoverage]:
    """Per sales code: where the DTx uses it and which harnesses know it.

    A code is *tracked* by a mapped harness when that harness's complexity
    lists it, and *missing from* one that was mapped to a family using the
    code but does not list it. A code used only by unmapped families cannot
    be judged either way and is reported as unassessed rather than as a gap.
    """
    by_code: Dict[str, CodeCoverage] = {}
    families_using: Dict[str, set] = {}

    for row in rows:
        expression = (getattr(row, "sales_code", "") or "").strip()
        if not expression:
            continue
        family = getattr(row, "harness_family", "")
        circuit = getattr(row, "circuit", "")
        for code in salescode.codes_in(expression):
            entry = by_code.setdefault(code, CodeCoverage(code=code))
            entry.dtx_rows += 1
            if family and family not in entry.families:
                entry.families.append(family)
            if circuit and circuit not in entry.circuits:
                entry.circuits.append(circuit)
            families_using.setdefault(code, set()).add(family)

    for pairing in entries:
        analysis = pairing.analysis
        label = f"{pairing.family} → {analysis.harness}"
        gaps = {gap.code for gap in analysis.code_gaps}
        for code, users in families_using.items():
            if pairing.family not in users:
                continue
            record = by_code[code]
            if code in gaps:
                if label not in record.missing_from:
                    record.missing_from.append(label)
            elif label not in record.tracked_by:
                record.tracked_by.append(label)

    for record in by_code.values():
        record.families.sort()
        record.circuits.sort()
        record.tracked_by.sort()
        record.missing_from.sort()
    return [by_code[code] for code in sorted(by_code)]


def assess(rows: Sequence, meta, issues: Sequence = (), entries: Sequence = (),
           fixes: Dict[str, str] | None = None) -> DtxQuality:
    """Measure one DTx, with whatever analysis has been run so far."""
    quality = DtxQuality(
        program=getattr(meta, "program", "") or "",
        phase=getattr(meta, "phase", "") or "",
        report_date=getattr(meta, "report_date", "") or "",
        rows=len(rows),
    )

    circuits, connectors, families, expressions, codes = set(), set(), set(), set(), set()
    for row in rows:
        circuit = getattr(row, "circuit", "")
        cnum = getattr(row, "cnum", "")
        family = getattr(row, "harness_family", "")
        expression = (getattr(row, "sales_code", "") or "").strip()
        if circuit:
            circuits.add(circuit)
        else:
            quality.blank_circuit += 1
        if cnum:
            connectors.add(cnum)
        else:
            quality.blank_cnum += 1
        if not getattr(row, "connector_pn", ""):
            quality.blank_connector_pn += 1
        if family:
            families.add(family)
        if expression:
            quality.conditioned_rows += 1
            expressions.add(expression)
            codes.update(salescode.codes_in(expression))
        else:
            quality.unconditional_rows += 1

    quality.circuits = len(circuits)
    quality.connectors = len(connectors)
    quality.families = len(families)
    quality.distinct_expressions = len(expressions)
    quality.distinct_codes = len(codes)

    quality.malformed_expressions = len(issues)
    quality.malformed_rows = sum(i.rows for i in issues)
    for issue in issues:
        quality.malformed_by_kind[issue.kind] = \
            quality.malformed_by_kind.get(issue.kind, 0) + 1
    quality.repaired_expressions = sum(
        1 for i in issues if i.expression in (fixes or {}))

    mapped_families = {p.family for p in entries}
    quality.families_mapped = len(mapped_families)
    quality.families_unmapped = sorted(families - mapped_families)
    quality.never_built_circuits = sum(
        1 for p in entries for c in p.analysis.circuits if c.classification == NEVER)
    quality.never_built_connectors = sum(
        1 for p in entries for c in p.analysis.cnums if c.classification == NEVER)
    quality.coverage = coverage(rows, entries)

    logger.info("DTx quality %s %s: %d row(s), %d finding(s)",
                quality.program, quality.phase, quality.rows, quality.finding_total)
    return quality
