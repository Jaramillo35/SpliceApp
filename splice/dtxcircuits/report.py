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

#: the column (and sheet) the cleanup notes land in — named by the request
CLEANUP_COLUMN = "Complexity Cleanup Notes"

KIND_CIRCUIT, KIND_CONNECTOR, KIND_GAP = "circuit", "connector", "gap"


def item_key(family: str, harness: str, kind: str, ident: str) -> str:
    """A stable handle for one selectable row, across refreshes and reruns."""
    return "|".join((family, harness, kind, ident))


@dataclass
class Entry:
    """One analysed pairing: a DTx family resolved against one harness file."""

    label: str
    family: str
    filename: str
    analysis: HarnessAnalysis


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


def circuit_note(analysis: HarnessAnalysis, circuit) -> str:
    """Why this circuit needs attention in the complexity file."""
    where = f"{analysis.harness} (def {analysis.def_id or '?'})"
    condition = circuit.expression or "(no sales code)"
    if circuit.classification == NEVER:
        return (f"No build of {where} satisfies {condition}. Either the circuit "
                f"does not belong on this harness, or a part number is missing "
                f"a code it should carry.")
    if circuit.untracked_codes:
        codes = ", ".join(circuit.untracked_codes)
        return (f"{codes} is not tracked by {where}, so {condition} is read as "
                f"applying to every build. Add the code to the complexity file "
                f"to make the applicability real.")
    if circuit.classification == NO_COMPLEXITY:
        return (f"No complexity file is mapped for {analysis.harness}, so "
                f"{condition} could not be resolved.")
    if circuit.classification == VARIANT:
        return (f"Carried by {len(circuit.builds_with)} of "
                f"{circuit.build_count} builds of {where} under {condition} — "
                f"confirm the split is intended.")
    if circuit.classification in (ALL_BUILDS, UNCONDITIONAL):
        return (f"Carried by every build of {where} under {condition} — "
                f"confirm the condition is still needed.")
    return f"Review {circuit.circuit} on {where} under {condition}."


def connector_note(analysis: HarnessAnalysis, cnum) -> str:
    where = f"{analysis.harness} (def {analysis.def_id or '?'})"
    condition = cnum.expression or "(no sales code)"
    if cnum.classification == NEVER:
        return (f"No build of {where} satisfies {condition}, so connector "
                f"{cnum.cnum} is never populated. Circuits affected: "
                f"{', '.join(cnum.circuits) or '—'}.")
    return (f"Connector {cnum.cnum} on {where} under {condition}; "
            f"{len(cnum.circuits)} circuit(s).")


def gap_note(analysis: HarnessAnalysis, gap) -> str:
    where = f"{analysis.harness} (def {analysis.def_id or '?'})"
    return (f"The DTx conditions on {gap.code} for {where} in "
            f"{gap.occurrences} row(s), but the complexity file does not track "
            f"it. Every circuit resting on it reads wider than the data can "
            f"justify. Circuits: {', '.join(gap.circuits) or '—'}.")


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
    for row in rows:
        ws.append(row)
        if note_col and ws.cell(ws.max_row, note_col).value:
            ws.cell(ws.max_row, note_col).fill = _NOTE_FILL
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


def build_report(entries: Iterable[Entry],
                 cleanup: Dict[str, CleanupSelection],
                 *, dtx_program: str = "", dtx_phase: str = "") -> bytes:
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
            circuit_rows.append([
                entry.family, a.harness, a.def_id, c.circuit, c.classification,
                c.expression or "", len(c.builds_with), c.build_count,
                ", ".join(c.builds_with), ", ".join(c.untracked_codes),
                ", ".join(c.pins),
                cleanup[key].note if key in cleanup else "",
            ])
    _sheet(wb, "Circuits", ["DTx family", "Harness", "Def id", "Circuit",
                            "Verdict", "Condition", "Builds with", "Builds",
                            "Carried by", "Untracked codes", "Pins",
                            CLEANUP_COLUMN], circuit_rows)

    cnum_rows = []
    for entry in entries:
        a = entry.analysis
        for c in a.cnums:
            key = item_key(entry.family, a.harness, KIND_CONNECTOR, c.cnum)
            cnum_rows.append([
                entry.family, a.harness, a.def_id, c.cnum, c.connector_pn,
                c.classification, c.expression or "", len(c.builds_with),
                c.build_count, len(c.circuits), ", ".join(c.circuits),
                ", ".join(c.untracked_codes),
                cleanup[key].note if key in cleanup else "",
            ])
    _sheet(wb, "Connectors", ["DTx family", "Harness", "Def id", "CNUM",
                              "Connector PN", "Verdict", "Condition",
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

    _sheet(wb, "Complexity Cleanup",
           ["DTx family", "Harness", "Type", "Item", "Verdict", "Condition",
            CLEANUP_COLUMN],
           [[s.family, s.harness, s.kind, s.ident, s.verdict, s.condition,
             s.note] for s in sorted(cleanup.values(),
                                     key=lambda s: (s.family, s.kind, s.ident))])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
