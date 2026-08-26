"""Domain models for individual harness-complexity generation.

Ported from WEAVE (harness-suite-v2, Milestones 3-4) into Splice. The matrix a
Systems Engineer reviews before generating an individual harness-complexity
file: every proposed value carries a :class:`ProposalClass` so the SE can see
what is confirmed by the master, what was inferred (carryover), and what still
needs judgment (combined sales-code expressions).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProposalClass(str, Enum):
    """How well-supported a proposed value is."""

    CONFIRMED = "confirmed"   # directly supported by an unambiguous source
    INFERRED = "inferred"     # determined from the rules but not stated directly
    UNCERTAIN = "uncertain"   # multiple interpretations possible
    MANUAL = "manual"         # reviewed or changed by the Systems Engineer
    EXCLUDED = "excluded"     # deleted / cancelled / invalid / manually excluded


@dataclass
class SalesCodeColumn:
    """One sales-code column proposed for the individual file."""

    code: str
    feature: str = ""            # feature description above the code (row 7)
    original_expr: str = ""      # the master row-9 cell text (retained for traceability)
    from_combined: bool = False  # split out of a separable OR-list (e.g. CJK/LEQ)
    source_col: str = ""         # master column letter
    klass: ProposalClass = ProposalClass.CONFIRMED


@dataclass
class CombinedExpr:
    """A master row-9 sales-code expression that could NOT be cleanly separated
    into independent codes (it uses AND ``+``/``&``, negation ``-``/``NO``, or
    grouping ``()``). Splitting it into single columns would misrepresent the
    applicability logic, so the Systems Engineer decides whether to include it
    and can name the sales code(s) it should appear as.
    """

    original_expr: str                       # e.g. "RS3+(CM5/CVM)"
    source_col: str                          # master column letter (its stable key)
    tokens: list[str] = field(default_factory=list)  # 3-char tokens found (reference only)
    feature: str = ""
    include: bool = False                    # SE decision — off by default
    manual_code: str = ""                    # SE-defined header for the column

    @property
    def key(self) -> str:
        return self.source_col or self.original_expr

    @property
    def header(self) -> str:
        """The column header to write when included (SE name, else the expression)."""
        return (self.manual_code or self.original_expr).strip()

    @property
    def is_equality(self) -> bool:
        """True for a pure equality like 'XH3=XH4' — the two codes are equivalent
        (no AND / negation / grouping). Unambiguous, so it is auto-resolved."""
        expr = self.original_expr.strip()
        return ("=" in expr and not any(op in expr for op in "+&/()-")
                and len([p for p in expr.split("=") if p.strip()]) >= 2)

    @property
    def output_codes(self) -> list[str]:
        """The sales-code column header(s) to write when included — each column
        carries the SAME per-row content:

        * a comma-separated SE definition ('XH3, XH4') becomes one column per code;
        * an equality expression from the master ('XH3=XH4') becomes one per side.

        Ordinary combined logic (``+``/``&``/``/``/``()``/``-``) stays one column.
        """
        if self.manual_code.strip():
            codes = [c.strip() for c in self.manual_code.split(",") if c.strip()]
            if codes:
                return list(dict.fromkeys(codes))
        expr = self.original_expr.strip()
        if "=" in expr and not any(op in expr for op in "+&/()-"):
            parts = [p.strip() for p in expr.split("=") if p.strip()]
            if len(parts) >= 2:
                return list(dict.fromkeys(parts))
        return [self.header]


@dataclass
class MatrixRow:
    """One part-number row of the applicability matrix."""

    variant_id: str
    current_pn: str
    previous_pn: str
    current_class: ProposalClass
    current_reason: str
    current_source: str                              # e.g. "DASH!AH10"
    excluded: bool = False
    symbols: dict[str, str] = field(default_factory=dict)          # code -> "X"/"G"
    symbol_class: dict[str, ProposalClass] = field(default_factory=dict)
    combined_symbols: dict[str, str] = field(default_factory=dict)  # CombinedExpr.key -> "X"/"G"
    partition_side: str = ""      # variant this PN belongs to (LEFT/RIGHT/DRIVER/…), "" = common


@dataclass
class FamilyMatrix:
    """The proposed individual-complexity content for one harness family."""

    worksheet: str
    canonical_family: str
    sales_codes: list[SalesCodeColumn] = field(default_factory=list)
    rows: list[MatrixRow] = field(default_factory=list)
    combined_exprs: list[CombinedExpr] = field(default_factory=list)  # unseparable — SE reviews
    dtx_codes: list[str] = field(default_factory=list)  # sales codes the DTx uses for THIS family
    harness_id: str = ""          # entered manually by the SE
    # Variant sides detected on master row 9 (e.g. ['LEFT','RIGHT']). Empty = not partitioned.
    partition_sides: list[str] = field(default_factory=list)
    # Program metadata parsed from the master family-sheet header (for the info table).
    year: str = ""
    vehicle: str = ""
    phase: str = ""
    harness_name: str = ""

    @property
    def complexity_codes(self) -> set[str]:
        """Sales codes present as columns in the complexity file for this family."""
        return {sc.code for sc in self.sales_codes}

    @property
    def excluded_count(self) -> int:
        return sum(1 for r in self.rows if r.excluded)

    @property
    def unresolved_count(self) -> int:
        """Rows that need SE review (uncertain P/N or any uncertain symbol)."""
        n = 0
        for r in self.rows:
            if r.current_class is ProposalClass.UNCERTAIN:
                n += 1
            elif any(c is ProposalClass.UNCERTAIN for c in r.symbol_class.values()):
                n += 1
        return n


@dataclass
class ComplexityFamilyChange:
    """Sales-code delta for one harness family between OLD and NEW master complexity."""

    worksheet: str
    canonical_family: str
    added_codes: list[str] = field(default_factory=list)
    removed_codes: list[str] = field(default_factory=list)

    @property
    def has_change(self) -> bool:
        return bool(self.added_codes or self.removed_codes)


@dataclass
class AffectedFamily:
    """A harness family flagged as affected, with the evidence."""

    family: str            # canonical name if known, else the raw DTx family name
    worksheet: str         # master worksheet, or "" when unmapped
    by_dtx: bool = False
    by_complexity: bool = False
    dtx_change_count: int = 0
    added_codes: list[str] = field(default_factory=list)
    removed_codes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    resolved: bool = True   # False when a DTx family can't be mapped to a worksheet
