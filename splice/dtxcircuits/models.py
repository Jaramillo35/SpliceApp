"""Domain models for per-harness circuit applicability.

The question this package answers: for one harness family, which circuits
does the DTx put on it, under which sales-code conditions, and which of that
harness's part numbers actually carry each circuit?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

#: How a circuit's condition resolves against one harness's build table.
UNCONDITIONAL = "unconditional"   # no sales code — every build carries it
ALL_BUILDS = "all builds"         # conditioned, but true for every build
VARIANT = "variant"               # true for some builds, not others
NEVER = "never built"             # true for no build — the finding worth reading
NO_COMPLEXITY = "no complexity"   # no complexity file loaded for this family


@dataclass(frozen=True)
class CircuitRow:
    """One DTx row: a circuit at a pin of a connector on a harness family."""

    harness_family: str
    circuit: str
    sales_code: str = ""          # raw expression, "" = unconditional
    cnum: str = ""
    pin: str = ""
    connector_pn: str = ""
    function: str = ""


@dataclass
class CircuitApplicability:
    """One circuit resolved against one harness's complexity table."""

    harness: str
    circuit: str
    classification: str
    expression: Optional[str]          # union of the row conditions; None = unconditional
    raw_expressions: List[str] = field(default_factory=list)
    builds_with: List[str] = field(default_factory=list)     # part numbers carrying it
    builds_without: List[str] = field(default_factory=list)
    #: Codes the condition names that this harness's complexity does not track.
    #: They are treated as PRESENT (unknown, not absent), so they can only widen
    #: applicability — never invent a missing circuit.
    untracked_codes: List[str] = field(default_factory=list)
    pins: List[str] = field(default_factory=list)            # "CNUM/pin" occurrences

    @property
    def build_count(self) -> int:
        return len(self.builds_with) + len(self.builds_without)

    @property
    def is_finding(self) -> bool:
        """A circuit the DTx puts on this harness that no build can carry."""
        return self.classification == NEVER

    @property
    def relies_on_untracked(self) -> bool:
        """Applicability leans on codes the complexity file does not track."""
        return bool(self.untracked_codes)


@dataclass
class CnumApplicability:
    """One connector (CNUM) resolved against a harness's complexity table.

    A connector is carried when ANY circuit on it is carried, so its condition
    is the union of its pins' conditions — the same rule a circuit uses across
    its own pins, one level up.
    """

    harness: str
    cnum: str
    classification: str
    expression: Optional[str]
    connector_pn: str = ""
    circuits: List[str] = field(default_factory=list)
    builds_with: List[str] = field(default_factory=list)
    builds_without: List[str] = field(default_factory=list)
    untracked_codes: List[str] = field(default_factory=list)
    pins: List[str] = field(default_factory=list)

    @property
    def build_count(self) -> int:
        return len(self.builds_with) + len(self.builds_without)

    @property
    def is_finding(self) -> bool:
        return self.classification == NEVER

    @property
    def relies_on_untracked(self) -> bool:
        return bool(self.untracked_codes)


@dataclass
class CodeGap:
    """A sales code the DTx uses for a family that its complexity does not track.

    Because unknown codes are treated as present, every circuit depending on
    one reads as applying more widely than the data can justify. This names the
    code and everything resting on it.
    """

    code: str
    circuits: List[str] = field(default_factory=list)
    cnums: List[str] = field(default_factory=list)
    occurrences: int = 0


@dataclass
class HarnessAnalysis:
    """Every circuit the DTx puts on one harness family, resolved."""

    harness: str
    def_id: str = ""
    builds: int = 0
    circuits: List[CircuitApplicability] = field(default_factory=list)
    cnums: List[CnumApplicability] = field(default_factory=list)
    code_gaps: List[CodeGap] = field(default_factory=list)
    #: codes the complexity tracks that no DTx circuit on this family uses
    unused_codes: List[str] = field(default_factory=list)

    def by_class(self, classification: str) -> List[CircuitApplicability]:
        return [c for c in self.circuits if c.classification == classification]

    @property
    def counts(self) -> dict:
        out = {k: 0 for k in
               (UNCONDITIONAL, ALL_BUILDS, VARIANT, NEVER, NO_COMPLEXITY)}
        for c in self.circuits:
            out[c.classification] = out.get(c.classification, 0) + 1
        return out

    @property
    def findings(self) -> List[CircuitApplicability]:
        return [c for c in self.circuits if c.is_finding]

    @property
    def untracked_codes(self) -> List[str]:
        """Every code this harness's circuits depend on but its complexity
        does not track — the actionable gap in the complexity file."""
        codes: set[str] = set()
        for c in self.circuits:
            codes.update(c.untracked_codes)
        return sorted(codes)

    @property
    def cnum_findings(self) -> List["CnumApplicability"]:
        return [c for c in self.cnums if c.is_finding]


@dataclass
class DtxMeta:
    """What the DTx export says about itself (never inferred from filename)."""

    program: str = ""
    phase: str = ""
    report_date: str = ""
    rows: int = 0
    families: int = 0
