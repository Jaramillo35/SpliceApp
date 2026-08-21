"""The vocabulary of an inline continuity study.

Small on purpose: six types carry everything the engine needs, and each maps
onto something an engineer already names at the bench.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

# -- verdicts ---------------------------------------------------------------

CONTINUOUS = "Continuous"
MISSING_CONTINUATION = "Missing continuation"
INCONSISTENT = "Inconsistent definition"
CONDITIONS_EXCLUSIVE = "Conditions exclusive"
NOT_IN_SUMMARY = "Not in Ckt Summary"
UNDETERMINED = "Undetermined"

#: The Circuit Summary states applicability twice — as an expression and as a
#: vector of part numbers. When they disagree the export is stale or damaged and
#: neither can be trusted, so it is escalated rather than silently preferred.
INTEGRITY = "Applicability sources disagree"

#: Verdicts that put a row in front of an engineer.
REVIEW_VERDICTS = frozenset(
    {MISSING_CONTINUATION, INCONSISTENT, CONDITIONS_EXCLUSIVE,
     NOT_IN_SUMMARY, UNDETERMINED, INTEGRITY}
)

#: Attribute differences are recorded, not judged: which ones are acceptable is
#: engineering judgement that belongs in a reviewable table, not in code.
MARK_SUFFIX = "suffix differs"
MARK_SIZE = "wire size differs"
MARK_MATERIAL = "material differs"
MARK_SALES_CODE = "sales code differs"

#: A wire at a cavity with no counterpart on the other side. The cavity as a
#: whole may still be continuous through another option, so this is a mark and
#: not a failure — but it is the mark most worth reading, because it is the one
#: an aggregated row hides completely.
MARK_UNPAIRED = "no counterpart"


@dataclass(frozen=True)
class Build:
    """One harness part number — one way the harness is actually built."""

    part_number: str
    symbol: str = ""
    codes: FrozenSet[str] = frozenset()


@dataclass
class Harness:
    """One harness in the study, and the builds it ships as."""

    name: str
    def_id: str
    builds: List[Build] = field(default_factory=list)
    complexity_codes: Set[str] = field(default_factory=set)
    complexity_file: str = ""
    in_scope: bool = True

    @property
    def has_complexity(self) -> bool:
        return bool(self.builds)

    @property
    def configurations(self) -> List[FrozenSet[str]]:
        """The sales-code combinations this harness is actually built in."""
        return [b.codes for b in self.builds]

    def __str__(self) -> str:
        return f"{self.name} ({self.def_id})"


@dataclass
class CircuitEnd:
    """One row of the Circuit Summary: a wire terminating in a cavity."""

    harness_id: str
    circuit: str
    suffix: str
    connector: str
    cavity: str
    device: str
    sales_code: str
    size: str = ""
    material: str = ""
    color: str = ""
    builds: FrozenSet[str] = frozenset()
    source_row: int = 0

    @property
    def identity(self) -> Tuple[str, str]:
        return (self.circuit, self.suffix)

    @property
    def label(self) -> str:
        return f"{self.circuit}{self.suffix}" if self.suffix else self.circuit


@dataclass(frozen=True)
class InlinePair:
    """Two connectors that mate across a harness interface."""

    connector_a: str
    harness_a: str
    connector_b: str
    harness_b: str
    resolved_by: str = "stem"

    @property
    def key(self) -> Tuple[str, str]:
        return (self.connector_a, self.connector_b)

    def __str__(self) -> str:
        return f"{self.connector_a} ↔ {self.connector_b}"


@dataclass
class Option:
    """One wire at a cavity, and the wire it pairs with on the other side.

    A cavity often holds several options — ``A934A`` and ``A934B`` split by
    sales code on one side, a single ``A934`` on the other. Keeping them as
    separate options rather than collapsing them into a list is what lets the
    report show one circuit per row, which is how an engineer reads it.
    """

    circuit_a: str = ""
    suffix_a: str = ""
    sales_code_a: str = ""
    size_a: str = ""
    material_a: str = ""
    circuit_b: str = ""
    suffix_b: str = ""
    sales_code_b: str = ""
    size_b: str = ""
    material_b: str = ""
    marks: List[str] = field(default_factory=list)
    matched: bool = False

    @property
    def label_a(self) -> str:
        return f"{self.circuit_a}{self.suffix_a}" if self.suffix_a else self.circuit_a

    @property
    def label_b(self) -> str:
        return f"{self.circuit_b}{self.suffix_b}" if self.suffix_b else self.circuit_b


@dataclass
class Finding:
    """One reviewable conclusion about one cavity."""

    verdict: str
    connector_a: str = ""
    harness_a: str = ""
    connector_b: str = ""
    harness_b: str = ""
    cavity: str = ""
    circuits_a: List[str] = field(default_factory=list)
    circuits_b: List[str] = field(default_factory=list)
    sales_codes_a: List[str] = field(default_factory=list)
    sales_codes_b: List[str] = field(default_factory=list)
    marks: List[str] = field(default_factory=list)
    options: List[Option] = field(default_factory=list)
    coverage_gap: str = ""
    reason: str = ""

    @property
    def needs_review(self) -> bool:
        return self.verdict in REVIEW_VERDICTS

    @property
    def inline(self) -> str:
        if not self.connector_b:
            return self.connector_a
        return f"{self.connector_a} ↔ {self.connector_b}"


@dataclass
class Gap:
    """Something missing, why the engine needs it, and what it blocks."""

    what: str
    why: str
    affects: str
    severity: str = "blocking"


@dataclass
class StudyResult:
    """Everything one run produced."""

    findings: List[Finding] = field(default_factory=list)
    gaps: List[Gap] = field(default_factory=list)
    harnesses: Dict[str, Harness] = field(default_factory=dict)
    pairs: List[InlinePair] = field(default_factory=list)
    cavities_checked: int = 0
    unused_complexity: List[str] = field(default_factory=list)

    @property
    def review(self) -> List[Finding]:
        return [f for f in self.findings if f.needs_review]

    @property
    def continuous(self) -> int:
        return sum(1 for f in self.findings if f.verdict == CONTINUOUS)

    @property
    def coverage_gaps(self) -> List[Finding]:
        """Continuous, but one side reaches vehicles the other does not."""
        return [f for f in self.findings if f.coverage_gap]

    @property
    def mark_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for finding in self.findings:
            for mark in finding.marks:
                counts[mark] = counts.get(mark, 0) + 1
        return counts

    def verdict_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for finding in self.findings:
            counts[finding.verdict] = counts.get(finding.verdict, 0) + 1
        return counts
