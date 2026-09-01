"""Export the applicability review, carrying the SE's cleanup selections.

The workbook is the hand-off: it repeats what the workbench showed, and adds
a **Complexity Cleanup Notes** column. A row the Systems Engineer ticked in
the workbench carries a written note saying what has to be fixed in the
complexity file; everything else leaves that column empty, so the column is a
work list rather than a wall of commentary.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from splice.dtxcircuits.models import (
    ALL_BUILDS,
    NEVER,
    NO_COMPLEXITY,
    UNCONDITIONAL,
    VARIANT,
    HarnessAnalysis,
)
from splice.inline import salescode

#: the column (and sheet) the cleanup notes land in — named by the request
CLEANUP_COLUMN = "Complexity Cleanup Notes"

KIND_CIRCUIT, KIND_CONNECTOR, KIND_GAP = "circuit", "connector", "gap"


def item_key(family: str, harness: str, kind: str, ident: str) -> str:
    """A stable handle for one selectable row, across refreshes and reruns."""
    return "|".join((family, harness, kind, ident))


@dataclass
class Entry:
    """One analysed pairing: a DTx family resolved against one harness file.

    ``original_*`` hold the conditions as the DTx actually stated them, before
    any sales-code repair was applied. The analysis runs on repaired rows, so
    without these the export would only ever show the corrected wording and
    there would be no record of what was changed or why a verdict moved.
    """

    label: str
    family: str
    filename: str
    analysis: HarnessAnalysis
    original_circuit_conditions: Dict[str, str] = field(default_factory=dict)
    original_cnum_conditions: Dict[str, str] = field(default_factory=dict)
    #: the complexity file itself. The analysis is a summary of it; the chart
    #: needs the builds and their codes to re-express a condition in the terms
    #: this harness actually tracks.
    complexity: object = None


@dataclass
class CleanupSelection:
    """What the SE ticked, and the note that will be exported for it."""

    key: str
    family: str
    harness: str
    kind: str
    ident: str
    verdict: str = ""
    condition: str = ""
    note: str = ""


def gap_codes(analysis: HarnessAnalysis) -> set:
    """Codes the DTx conditions on that this harness's complexity never lists."""
    return {gap.code for gap in analysis.code_gaps}


def inert_codes(expression: str, gaps: set) -> List[str]:
    """The codes in ``expression`` this harness's complexity cannot see.

    A code the complexity does not track is treated as present, so it can
    never narrow anything: leaving it in the condition only makes the item
    look conditional when it is not.
    """
    if not expression or not gaps:
        return []
    return sorted({code for code in salescode.codes_in(expression)
                   if code in gaps})


def removal_hint(expression: str, gaps: set) -> str:
    """The one fix, phrased the same way everywhere it appears."""
    hits = inert_codes(expression, gaps)
    if not hits:
        return ""
    codes = ", ".join(hits)
    return f" Remove {codes}, or add it to the complexity file."


def _inert_note(condition: str, hits: List[str]) -> str:
    codes = ", ".join(hits)
    return (f"{condition} reads as always true — {codes} not in the complexity "
            f"file. Remove {codes}, or add it.")


def circuit_note(analysis: HarnessAnalysis, circuit) -> str:
    """Why this circuit needs attention. One line, no restated columns."""
    condition = circuit.expression or "(no sales code)"
    gaps = gap_codes(analysis)
    hits = inert_codes(circuit.expression, gaps)
    if circuit.classification == NEVER:
        return (f"Never built — no build satisfies {condition}."
                + removal_hint(circuit.expression, gaps))
    if hits or circuit.untracked_codes:
        return _inert_note(condition,
                           hits or sorted(circuit.untracked_codes))
    if circuit.classification == NO_COMPLEXITY:
        return f"No complexity file mapped, so {condition} was not resolved."
    if circuit.classification == VARIANT:
        return (f"{len(circuit.builds_with)} of {circuit.build_count} builds "
                f"under {condition} — confirm the split is intended.")
    if circuit.classification in (ALL_BUILDS, UNCONDITIONAL):
        return (f"Every build carries it under {condition} — confirm the "
                f"condition is still needed.")
    return f"Review under {condition}."


def connector_note(analysis: HarnessAnalysis, cnum) -> str:
    condition = cnum.expression or "(no sales code)"
    gaps = gap_codes(analysis)
    hits = inert_codes(cnum.expression, gaps)
    if cnum.classification == NEVER:
        return (f"Never populated — no build satisfies {condition}."
                + removal_hint(cnum.expression, gaps))
    if hits:
        return _inert_note(condition, hits)
    if cnum.classification in (ALL_BUILDS, UNCONDITIONAL):
        return (f"Every build populates it under {condition} — confirm the "
                f"condition is still needed.")
    return f"{len(cnum.circuits)} circuit(s) under {condition}."


def gap_note(analysis: HarnessAnalysis, gap) -> str:
    return (f"Sales code {gap.code} is in the DTx report but not in the "
            f"complexity file.")


def selection_for(entry: Entry, kind: str, ident: str) -> Optional[CleanupSelection]:
    """Build the selection record (and its note) for one row of one entry."""
    analysis = entry.analysis
    if kind == KIND_CIRCUIT:
        item = next((c for c in analysis.circuits if c.circuit == ident), None)
        if item is None:
            return None
        return CleanupSelection(
            key=item_key(entry.family, analysis.harness, kind, ident),
            family=entry.family, harness=analysis.harness, kind=kind,
            ident=ident, verdict=item.classification,
            condition=item.expression or "", note=circuit_note(analysis, item))
    if kind == KIND_CONNECTOR:
        item = next((c for c in analysis.cnums if c.cnum == ident), None)
        if item is None:
            return None
        return CleanupSelection(
            key=item_key(entry.family, analysis.harness, kind, ident),
            family=entry.family, harness=analysis.harness, kind=kind,
            ident=ident, verdict=item.classification,
            condition=item.expression or "", note=connector_note(analysis, item))
    if kind == KIND_GAP:
        item = next((g for g in analysis.code_gaps if g.code == ident), None)
        if item is None:
            return None
        return CleanupSelection(
            key=item_key(entry.family, analysis.harness, kind, ident),
            family=entry.family, harness=analysis.harness, kind=kind,
            ident=ident, verdict="sales-code gap", condition="",
            note=gap_note(analysis, item))
    return None


def auto_select(entries: Iterable[Entry],
                dismissed: Optional[set] = None) -> Dict[str, CleanupSelection]:
    """The findings worth putting in front of the customer, pre-ticked.

    Never-built circuits and connectors, and every sales-code gap: each is a
    place the DTx cannot be reconciled with complexity built from the
    customer's own information.

    Also taken: anything built on *every* build whose condition contains one
    of those gap codes. An untracked code is read as present, so it cannot
    narrow anything — the condition only looks like a condition. That is the
    other half of the same defect, and it carries a concrete fix (drop the
    code), so it belongs in the cleanup list rather than being left for the
    SE to find by hand.

    Anything the SE has explicitly unticked is left alone — a proposal that
    reappears every run is not a proposal.
    """
    dismissed = dismissed or set()
    picked: Dict[str, CleanupSelection] = {}

    def take(entry: Entry, kind: str, ident: str) -> None:
        key = item_key(entry.family, entry.analysis.harness, kind, ident)
        if key in dismissed or key in picked:
            return
        selection = selection_for(entry, kind, ident)
        if selection:
            picked[key] = selection

    for entry in entries:
        analysis = entry.analysis
        gaps = gap_codes(analysis)
        inert = lambda expression: bool(removal_hint(expression, gaps))  # noqa: E731
        for circuit in analysis.circuits:
            if circuit.classification == NEVER or (
                    circuit.classification in (ALL_BUILDS, UNCONDITIONAL)
                    and inert(circuit.expression)):
                take(entry, KIND_CIRCUIT, circuit.circuit)
        for connector in analysis.cnums:
            if connector.classification == NEVER or (
                    connector.classification in (ALL_BUILDS, UNCONDITIONAL)
                    and inert(connector.expression)):
                take(entry, KIND_CONNECTOR, connector.cnum)
        for gap in analysis.code_gaps:
            take(entry, KIND_GAP, gap.code)
    return picked


# --------------------------------------------------------------------------
# workbook
# --------------------------------------------------------------------------

_HEAD_FILL = PatternFill("solid", fgColor="1F3B57")
_HEAD_FONT = Font(bold=True, color="FFFFFF")
_NOTE_FILL = PatternFill("solid", fgColor="FFF3CD")


def _sheet(wb: Workbook, title: str, headers: List[str], rows: List[list],
           first: bool = False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title[:31]
    ws.append(headers)
    for cell in ws[1]:
        cell.fill, cell.font = _HEAD_FILL, _HEAD_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    note_col = headers.index(CLEANUP_COLUMN) + 1 if CLEANUP_COLUMN in headers else None
    # The row index is tracked, not read back: ws.max_row rescans every cell
    # written so far, which turns a long sheet quadratic.
    line_no = 1
    for row in rows:
        ws.append(row)
        line_no += 1
        if note_col and ws.cell(line_no, note_col).value:
            ws.cell(line_no, note_col).fill = _NOTE_FILL
    widths = [12] * len(headers)
    for index, header in enumerate(headers):
        longest = max([len(str(header))] + [len(str(r[index])) for r in rows[:400]]
                      or [10])
        widths[index] = min(max(12, longest + 2), 70)
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = ws.dimensions
    return ws


def _quality_sheets(wb: Workbook, q) -> None:
    """Two sheets written for the customer: what the export got right, and
    where each sales code is and is not known."""
    _sheet(wb, "Data quality", ["Measure", "Value", "What it means"], [
        ["Programme", q.program or "?", "Read from the DTx title block"],
        ["Phase", q.phase or "?", ""],
        ["Report date", q.report_date or "?", ""],
        ["", "", ""],
        ["Rows", q.rows, "Circuit/connector rows read"],
        ["Circuits", q.circuits, ""],
        ["Connectors", q.connectors, ""],
        ["Harness families", q.families, ""],
        ["Conditioned rows", f"{q.conditioned_rows} ({q.conditioned_share:.0%})",
         "Rows carrying a sales-code condition"],
        ["Unconditional rows", q.unconditional_rows, "Built on every "
         "configuration"],
        ["Distinct expressions", q.distinct_expressions, ""],
        ["Distinct sales codes", q.distinct_codes, ""],
        ["", "", ""],
        ["FINDINGS", "", "Each one is something to correct in the next export"],
        ["Malformed expressions", q.malformed_expressions,
         "No boolean operator between codes — the expression is false for "
         "every configuration, so its circuits read as never built"],
        ["  rows affected", q.malformed_rows, ""],
        ["  repaired in review", q.repaired_expressions,
         "The Systems Engineer supplied the intended expression; see the "
         "Sales-code repairs sheet"],
        ["Never-built circuits", q.never_built_circuits,
         "No configuration of the mapped harness satisfies the condition"],
        ["Never-built connectors", q.never_built_connectors, ""],
        ["Codes tracked nowhere", len(q.codes_not_tracked_anywhere),
         "Used by the DTx, absent from every complexity file it was checked "
         "against"],
        ["Codes partly tracked", len(q.codes_partially_tracked),
         "Known to some harnesses and not others"],
        ["", "", ""],
        ["Families assessed", q.families_mapped, ""],
        ["Families not assessed", len(q.families_unmapped),
         ", ".join(q.families_unmapped)],
    ] + [[k, v, ""] for k, v in sorted(q.malformed_by_kind.items())])

    _sheet(wb, "Sales-code coverage",
           ["Sales code", "Status", "DTx rows", "Used by families",
            "Tracked by", "Missing from", "Circuits"],
           [[x.code, x.status, x.dtx_rows, ", ".join(x.families),
             ", ".join(x.tracked_by) or "—", ", ".join(x.missing_from) or "—",
             ", ".join(x.circuits[:20])] for x in q.coverage])


def build_report(entries: Iterable[Entry],
                 cleanup: Dict[str, CleanupSelection],
                 *, dtx_program: str = "", dtx_phase: str = "",
                 repairs: Optional[Dict[str, str]] = None,
                 repair_context: Optional[Dict[str, dict]] = None,
                 quality=None, charts=None) -> bytes:
    """The review workbook, with the cleanup notes folded into every sheet."""
    entries = list(entries)
    wb = Workbook()

    _sheet(wb, "Read Me", ["Circuit applicability review"], [
        [f"DTx programme {dtx_program or '?'} · phase {dtx_phase or '?'}"],
        [f"Generated {date.today():%Y-%m-%d}"],
        [""],
        ["Each DTx harness family is resolved against the complexity file(s) "
         "mapped to it. A family may be mapped to several harnesses; each "
         "pairing is reported separately."],
        [""],
        [f"'{CLEANUP_COLUMN}' carries a note only for the rows the Systems "
         "Engineer selected in the workbench. Those rows are also collected on "
         "the Complexity Cleanup sheet as a work list."],
        [""],
        ["Every circuit and connector shows its condition twice: 'as in DTx' is "
         "what the export stated, 'as decided' is what was analysed after any "
         "sales-code repair. 'Repaired' marks the rows where they differ, and "
         "the Sales-code repairs sheet lists each decision once with what "
         "depended on it."],
        [""],
        ["Verdicts: unconditional (no sales code, every build); all builds "
         "(conditioned but true for all); variant (some part numbers); never "
         "built (no build satisfies the condition — a defect or a missing "
         "code); no complexity (nothing mapped)."],
        ["A sales code the DTx uses that the complexity file does not track is "
         "treated as PRESENT, so circuits resting on it read wider than the "
         "data can justify."],
    ], first=True)

    circuit_rows = []
    for entry in entries:
        a = entry.analysis
        for c in a.circuits:
            key = item_key(entry.family, a.harness, KIND_CIRCUIT, c.circuit)
            decided = c.expression or ""
            # an absent original means "not recorded", never "changed" — the
            # Repaired flag must only fire on a difference we actually saw
            original = entry.original_circuit_conditions.get(c.circuit, decided)
            circuit_rows.append([
                entry.family, a.harness, a.def_id, c.circuit, c.classification,
                original, decided, "yes" if original != decided else "",
                len(c.builds_with), c.build_count,
                ", ".join(c.builds_with), ", ".join(c.untracked_codes),
                ", ".join(c.pins),
                cleanup[key].note if key in cleanup else "",
            ])
    if quality is not None:
        _quality_sheets(wb, quality)

    _sheet(wb, "Circuits", ["DTx family", "Harness", "Def id", "Circuit",
                            "Verdict", "Condition as in DTx",
                            "Condition as decided", "Repaired",
                            "Builds with", "Builds",
                            "Carried by", "Untracked codes", "Pins",
                            CLEANUP_COLUMN], circuit_rows)

    cnum_rows = []
    for entry in entries:
        a = entry.analysis
        for c in a.cnums:
            key = item_key(entry.family, a.harness, KIND_CONNECTOR, c.cnum)
            decided = c.expression or ""
            original = entry.original_cnum_conditions.get(c.cnum, decided)
            cnum_rows.append([
                entry.family, a.harness, a.def_id, c.cnum, c.connector_pn,
                c.classification, original, decided,
                "yes" if original != decided else "", len(c.builds_with),
                c.build_count, len(c.circuits), ", ".join(c.circuits),
                ", ".join(c.untracked_codes),
                cleanup[key].note if key in cleanup else "",
            ])
    _sheet(wb, "Connectors", ["DTx family", "Harness", "Def id", "CNUM",
                              "Connector PN", "Verdict", "Condition as in DTx",
                              "Condition as decided", "Repaired",
                              "Builds with", "Builds", "# circuits", "Circuits",
                              "Untracked codes", CLEANUP_COLUMN], cnum_rows)

    gap_rows = []
    for entry in entries:
        a = entry.analysis
        for g in a.code_gaps:
            key = item_key(entry.family, a.harness, KIND_GAP, g.code)
            gap_rows.append([
                entry.family, a.harness, a.def_id, g.code, g.occurrences,
                ", ".join(g.circuits), ", ".join(g.cnums),
                cleanup[key].note if key in cleanup else "",
            ])
    _sheet(wb, "Sales-code gaps", ["DTx family", "Harness", "Def id",
                                   "Sales code", "DTx rows", "Circuits",
                                   "Connectors", CLEANUP_COLUMN], gap_rows)

    repair_rows = []
    for original in sorted(repairs or {}):
        context = (repair_context or {}).get(original, {})
        repair_rows.append([
            original, (repairs or {})[original],
            context.get("kind", ""), context.get("rows", ""),
            ", ".join(context.get("families", [])),
            ", ".join(context.get("circuits", [])),
        ])
    _sheet(wb, "Sales-code repairs",
           ["Expression as in DTx", "Expression as decided", "Problem",
            "DTx rows", "Families", "Circuits"], repair_rows)

    if charts:
        # Written last so it sits at the end of the book, but in the exact
        # layout splice.inline.summary parses: this sheet is also an input.
        from splice.dtxcircuits.chart import write_chart_sheet
        write_chart_sheet(wb, charts, dtx_program, dtx_phase)

    _sheet(wb, "Complexity Cleanup",
           ["DTx family", "Harness", "Type", "Item", "Verdict", "Condition",
            CLEANUP_COLUMN],
           [[s.family, s.harness, s.kind, s.ident, s.verdict, s.condition,
             s.note] for s in sorted(cleanup.values(),
                                     key=lambda s: (s.family, s.kind, s.ident))])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
