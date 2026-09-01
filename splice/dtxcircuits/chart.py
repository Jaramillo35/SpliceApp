"""A circuit chart per harness family: which part number carries which wire.

This is the thing the SE has been reconstructing by hand. Everything it needs
is already resolved by the time the review is done — the DTx gives the circuit
ends (circuit, connector, cavity, device, condition) and the complexity gives
the part numbers and the codes each one carries — so the chart is not new
analysis, it is the analysis written out in the shape people read.

The layout deliberately matches the **Circuit Summary** that Circuit Health
takes as input: a block per harness, opened by a ``<Family> - <def id>`` /
``Circuit`` header row carrying ``X~<part number>`` columns, then one row per
circuit end marked ``X`` under every build that carries it. Two reasons for
copying an existing format rather than inventing one:

* SEs already read it. A chart in a familiar shape needs no explanation.
* It round-trips. What this module writes, ``splice.inline.summary`` reads
  back, so a DTx-derived chart can be fed straight into Circuit Health and
  compared against the CAD-derived one. A test holds that both ways.

The one thing it cannot invent is wire physicals — size, material, colour are
not in the DTx, so those columns are left empty rather than guessed. A blank
cell says "not stated"; a made-up gauge would be read as fact.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from splice.dtxcircuits import conventions
from splice.dtxcircuits.models import (
    ALL_BUILDS, NEVER, NO_COMPLEXITY, VARIANT,
)
from splice.inline import salescode
from splice.inline.complexity import applies_in
from splice.inline.summary import (
    COL_CAV,
    COL_CIRCUIT,
    COL_CNUM,
    COL_COLOR,
    COL_DEVICE,
    COL_FAMILY,
    COL_MATERIAL,
    COL_SALES_CODE,
    COL_SIZE,
    COL_SUFFIX,
    FIRST_BUILD_COL,
    SHEET,
)

logger = logging.getLogger(__name__)

MARK = "X"

#: Column headers for the human-facing sheet. Positions are fixed by the
#: Circuit Summary contract, so the labels are placed, not appended.
_LABELS = {
    COL_FAMILY: "Harness Family",
    COL_CIRCUIT: "Circuit",
    COL_SUFFIX: "Suffix",
    COL_SIZE: "Size",
    COL_MATERIAL: "Material",
    COL_COLOR: "Color",
    COL_CNUM: "CNUM",
    COL_CAV: "Cavity",
    COL_DEVICE: "Device",
    COL_SALES_CODE: "Sales Code",
}


@dataclass
class ChartRow:
    """One circuit end, and the part numbers that carry it."""

    circuit: str
    cnum: str = ""
    cavity: str = ""
    device: str = ""
    connector_pn: str = ""
    #: the condition as the DTx states it for this circuit, flowed across
    #: every harness the circuit reaches
    expression: str = ""
    #: the same condition re-expressed in the codes THIS harness tracks
    harness_expression: str = ""
    classification: str = ""
    builds: List[str] = field(default_factory=list)
    #: a wire running to a generated splice rather than to a device
    is_splice: bool = False

    def carried_by(self, part_number: str) -> bool:
        return part_number in self.builds

    @property
    def is_finding(self) -> bool:
        return self.classification == NEVER

    def marks(self, part_numbers: Sequence[str]) -> List[str]:
        return [MARK if self.carried_by(pn) else "" for pn in part_numbers]


@dataclass
class Chart:
    """One harness family resolved against one complexity file."""

    family: str
    harness: str
    def_id: str = ""
    part_numbers: List[str] = field(default_factory=list)
    rows: List[ChartRow] = field(default_factory=list)
    #: circuit -> generated splice name, for the circuits that needed one
    splices: Dict[str, str] = field(default_factory=dict)

    @property
    def block_title(self) -> str:
        """``BODY_LEFT - 7010`` — the header the Circuit Summary parser keys on."""
        return f"{self.harness} - {self.def_id}" if self.def_id else self.harness

    @property
    def circuits(self) -> int:
        return len({row.circuit for row in self.rows})

    @property
    def findings(self) -> int:
        return sum(1 for row in self.rows if row.is_finding)

    def coverage(self, part_number: str) -> int:
        """How many circuit ends this part number carries."""
        return sum(1 for row in self.rows if row.carried_by(part_number))


#: A circuit reaching this many cavities inside one harness cannot be run as
#: a single wire — the branches have to meet somewhere, and that somewhere is
#: a splice.
SPLICE_MIN_ENDS = 3


def flowed_conditions(rows: Sequence) -> Dict[str, Optional[str]]:
    """One condition per circuit, unioned across every harness it reaches.

    A circuit is one wire. It does not become conditional at a harness
    boundary, so the condition the DTx states anywhere on it applies to all of
    it — that is what "let the sales codes flow through the circuit" means.
    The occurrences are OR-ed, and a single unconditional occurrence (a blank
    cell, or a bare universal code) makes the whole circuit unconditional,
    returned as ``None`` because no expression says "always".
    """
    parts: Dict[str, Optional[List[str]]] = {}
    for row in rows:
        circuit = getattr(row, "circuit", "")
        if not circuit:
            continue
        condition = conventions.effective_condition(getattr(row, "sales_code", ""))
        if circuit not in parts:
            parts[circuit] = []
        if parts[circuit] is None:
            continue
        if condition is None:
            parts[circuit] = None
        else:
            parts[circuit].append(f"({condition})")
    return {circuit: (None if group is None else "/".join(sorted(set(group))) or None)
            for circuit, group in parts.items()}


def carrying_builds(condition: Optional[str], complexity) -> List[str]:
    """The part numbers of ``complexity`` that satisfy ``condition``."""
    if complexity is None or not getattr(complexity, "builds", None):
        return []
    if condition is None:
        return [b.part_number for b in complexity.builds]
    vocabulary = getattr(complexity, "complexity_codes", set())
    return [b.part_number for b in complexity.builds
            if applies_in(condition, b.codes, vocabulary)]


def harness_expression(condition: Optional[str], builds: Sequence[str],
                       complexity) -> str:
    """Re-express a condition in the codes THIS harness actually tracks.

    The DTx writes one condition for the whole circuit, in whatever codes the
    programme uses. A harness's complexity only tracks some of them, so the
    same condition has to be restated per harness — otherwise the chart cites
    codes that harness has no column for.

    A condition already written entirely in codes this harness tracks is kept
    as it is. It selects the right builds by construction, and rewriting it
    would hand the SE a different-looking expression for no gain — the DTx
    ``(QA1)`` came back as ``-QA2`` before this rule, which is equally true
    and needlessly unfamiliar.

    Only where the condition leans on a code this harness has no column for is
    it restated, and then from the outcome rather than the text: take the part
    numbers it selects, and ask the Splice Generation engine for an expression
    selecting exactly those. Returns ``""`` for "every build" and for "no
    build", since neither is a condition, and falls back to ``""`` rather than
    guessing when the generated expression does not verify.
    """
    if complexity is None or not getattr(complexity, "builds", None):
        return ""
    everything = [b.part_number for b in complexity.builds]
    carried = [pn for pn in everything if pn in set(builds)]
    if not carried or len(carried) == len(everything):
        return ""

    vocabulary = getattr(complexity, "complexity_codes", set())
    if condition and all(code in vocabulary
                         for code in salescode.codes_in(condition)):
        return condition

    code_map = {b.part_number: set(b.codes) for b in complexity.builds}
    try:
        from splice.splice_gen import (generate_expression_for_selected_pns,
                                       validate_generated_expression)
        expression = generate_expression_for_selected_pns(carried, code_map)
        if expression and validate_generated_expression(expression, carried, code_map):
            return expression
        if expression:
            logger.info("Generated expression for %s did not verify; dropped",
                        getattr(complexity, "name", "?"))
    except Exception as exc:  # noqa: BLE001 — a chart must never fail to build
        logger.info("Could not restate a condition for %s: %s",
                    getattr(complexity, "name", "?"), exc)
    return ""


def build_charts(entries: Iterable, rows: Sequence,
                 splice_min_ends: int = SPLICE_MIN_ENDS) -> List[Chart]:
    """One chart per family × harness pairing, from the resolved analysis.

    ``rows`` are the DTx circuit rows the analysis was run on — the repaired
    ones, so the chart shows what was actually resolved rather than what the
    export said before the SE fixed it.
    """
    by_family: Dict[str, List] = {}
    for row in rows:
        by_family.setdefault(getattr(row, "harness_family", ""), []).append(row)
    # conditions are flowed over ALL rows, not per family: a circuit that is
    # conditional where the DTx happens to state it is conditional everywhere
    flowed = flowed_conditions(rows)

    charts: List[Chart] = []
    for entry in entries:
        analysis = entry.analysis
        complexity = getattr(entry, "complexity", None)
        family_rows = by_family.get(entry.family, [])

        applicability = {c.circuit: c for c in analysis.circuits}
        connector_pn = {}
        for row in family_rows:
            if row.cnum and row.cnum not in connector_pn:
                connector_pn[row.cnum] = row.connector_pn or ""

        chart = Chart(family=entry.family, harness=analysis.harness,
                      def_id=analysis.def_id,
                      part_numbers=_part_numbers(analysis, complexity))

        # resolved once per circuit, not once per end: the condition is a
        # property of the wire, so every end of it is carried identically
        resolved: Dict[str, tuple] = {}

        seen = set()
        for row in family_rows:
            key = (row.circuit, row.cnum, row.pin)
            if not row.circuit or key in seen:
                continue
            seen.add(key)
            if row.circuit not in resolved:
                condition = flowed.get(row.circuit)
                if complexity is not None:
                    builds = carrying_builds(condition, complexity)
                    restated = harness_expression(condition, builds, complexity)
                else:
                    # No complexity file to resolve against. Fall back to what
                    # the analysis already worked out rather than reporting
                    # nothing carried — an empty chart would read as every
                    # circuit being never built, which is a lie, not a gap.
                    item = applicability.get(row.circuit)
                    builds = list(item.builds_with) if item else []
                    restated = ""
                resolved[row.circuit] = (
                    condition or "", builds, restated,
                    _classify(builds, chart.part_numbers))
            expression, builds, restated, classification = resolved[row.circuit]
            chart.rows.append(ChartRow(
                circuit=row.circuit, cnum=row.cnum, cavity=row.pin,
                device=row.function or "",
                connector_pn=connector_pn.get(row.cnum, ""),
                expression=expression, harness_expression=restated,
                classification=classification, builds=list(builds)))

        _add_splices(chart, splice_min_ends)
        chart.rows.sort(key=lambda r: (r.circuit, r.cnum, _cavity_key(r.cavity)))
        charts.append(chart)

    logger.info("Built %d circuit chart(s), %d row(s), %d splice(s)",
                len(charts), sum(len(c.rows) for c in charts),
                sum(len(c.splices) for c in charts))
    return charts


def _classify(builds: Sequence[str], part_numbers: Sequence[str]) -> str:
    if not part_numbers:
        return NO_COMPLEXITY
    if not builds:
        return NEVER
    return ALL_BUILDS if len(builds) == len(part_numbers) else VARIANT


def _add_splices(chart: Chart, minimum: int) -> None:
    """Give every circuit with three or more ends a splice to meet at.

    Two ends is a wire. Three is a branch, and a branch has to join somewhere
    physically — so the chart says where, rather than leaving the SE to infer
    it. The splice is named the way Splice Generation already names them,
    ``S<circuit>`` plus a letter, and each branch lands on its own cavity.

    Cavities run A, B, C … and continue AA, AB … past 26. The SE asked for
    A-Z; real nets go far beyond it (one circuit in 2028RU X2_A has 269 ends),
    and silently truncating at Z would drop wires.
    """
    if minimum <= 0:
        return
    by_circuit: Dict[str, List[ChartRow]] = {}
    for row in chart.rows:
        by_circuit.setdefault(row.circuit, []).append(row)

    for circuit, ends in sorted(by_circuit.items()):
        if len(ends) < minimum:
            continue
        name = f"S{circuit}{_int_to_alpha_suffix(0)}"
        chart.splices[circuit] = name
        for index, end in enumerate(ends):
            # one wire per branch, device end to splice end; it carries
            # exactly what its branch carries
            chart.rows.append(ChartRow(
                circuit=circuit, cnum=name,
                cavity=_int_to_alpha_suffix(index),
                device=f"SPLICE {name}",
                expression=end.expression,
                harness_expression=end.harness_expression,
                classification=end.classification,
                builds=list(end.builds), is_splice=True))


def _int_to_alpha_suffix(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA. The scheme Splice Generation already uses."""
    result, value = "", index
    while True:
        value, remainder = divmod(value, 26)
        result = chr(ord("A") + remainder) + result
        if value == 0:
            break
        value -= 1
    return result


def _part_numbers(analysis, complexity=None) -> List[str]:
    """Every part number of the harness, in a stable order.

    The complexity file is the authority when it is available: it lists every
    build, including one that carries nothing, and an empty column is itself
    the finding. Without it, fall back to whatever the analysis mentions.
    """
    if complexity is not None and getattr(complexity, "builds", None):
        return [b.part_number for b in complexity.builds]
    ordered: List[str] = []
    for circuit in analysis.circuits:
        for part in list(circuit.builds_with) + list(circuit.builds_without):
            if part not in ordered:
                ordered.append(part)
    return sorted(ordered)


def _cavity_key(value: str):
    """Order cavities the way they are allocated, not the way they spell.

    Numbers sort numerically (2 before 10). Letters sort by length first, so a
    splice runs A, B … Z, AA, AB — plain alphabetical order would file AA
    between A and B and scatter a 269-way ground net.
    """
    text = (value or "").strip()
    head = text.split(":")[0]
    if head.isdigit():
        return (0, len(head), int(head), text)
    return (1, len(head), 0, text)


# --------------------------------------------------------------------------
# workbook
# --------------------------------------------------------------------------

_TITLE_FONT = Font(bold=True, size=12)
_BLOCK_FILL = PatternFill("solid", fgColor="1F3B57")
_BLOCK_FONT = Font(bold=True, color="FFFFFF")
_MARK_FONT = Font(bold=True)
_NEVER_FILL = PatternFill("solid", fgColor="F8D7DA")

# Hoisted, not built per cell. A real programme is ~5,400 circuit ends against
# ~20 part numbers — 115,000 mark cells — and constructing a style object for
# each one cost more than everything else in this module put together.
_CENTER = Alignment(horizontal="center")
_BLOCK_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)


def write_chart_sheet(wb: Workbook, charts: Sequence[Chart],
                      program: str = "", phase: str = "") -> None:
    """Write the blocked Circuit Summary sheet into ``wb``.

    The sheet name and geometry are the ones ``splice.inline.summary`` parses,
    so Circuit Health can take this workbook as an input unchanged.

    The row index is tracked here rather than read back from the sheet.
    ``ws.max_row`` rescans every cell written so far, so styling each row via
    ``ws[ws.max_row]`` is quadratic: on a real programme (~5,400 circuit ends
    against ~20 part numbers) that alone took 33 seconds and, run on the event
    loop, dropped the browser's connection.
    """
    ws = wb.create_sheet(SHEET)
    ws.append(["Circuit Summary", " ".join(p for p in (program, phase) if p)])
    ws.cell(1, 1).font = _TITLE_FONT
    line_no = 1

    widest = 0
    for chart in charts:
        span = len(chart.part_numbers)
        widest = max(widest, span)

        header = [""] * (FIRST_BUILD_COL + span)
        header[COL_FAMILY] = chart.block_title
        header[COL_CIRCUIT] = "Circuit"
        for offset, part in enumerate(chart.part_numbers):
            header[FIRST_BUILD_COL + offset] = f"{MARK}~{part}"
        ws.append(header)
        line_no += 1
        for column in (COL_FAMILY + 1, COL_CIRCUIT + 1):
            cell = ws.cell(line_no, column)
            cell.fill, cell.font, cell.alignment = _BLOCK_FILL, _BLOCK_FONT, _BLOCK_ALIGN
        for offset in range(span):
            cell = ws.cell(line_no, FIRST_BUILD_COL + offset + 1)
            cell.fill, cell.font, cell.alignment = _BLOCK_FILL, _BLOCK_FONT, _BLOCK_ALIGN

        for row in chart.rows:
            line = [""] * (FIRST_BUILD_COL + span)
            line[COL_FAMILY] = chart.family
            line[COL_CIRCUIT] = row.circuit
            line[COL_CNUM] = row.cnum
            line[COL_CAV] = row.cavity
            line[COL_DEVICE] = row.device
            # The Circuit Summary's own Sales Code column carries the harness
            # form, because that is the one true of this block's part numbers.
            # The DTx form rides in the Suffix column, which the parser reads
            # but nothing downstream conditions on.
            line[COL_SALES_CODE] = row.harness_expression or row.expression
            if row.harness_expression and row.harness_expression != row.expression:
                line[COL_SUFFIX] = row.expression
            marks = row.marks(chart.part_numbers)
            for offset, mark in enumerate(marks):
                line[FIRST_BUILD_COL + offset] = mark
            ws.append(line)
            line_no += 1

            # Only the cells that carry something are styled: an empty cell
            # gains nothing from being centred.
            for offset, mark in enumerate(marks):
                if mark:
                    cell = ws.cell(line_no, FIRST_BUILD_COL + offset + 1)
                    cell.alignment, cell.font = _CENTER, _MARK_FONT
            # A circuit no build carries is the whole point of the chart, and
            # an entirely empty row is easy to scroll past — so it is coloured.
            if row.is_finding:
                for column in range(1, FIRST_BUILD_COL + span + 1):
                    ws.cell(line_no, column).fill = _NEVER_FILL

        ws.append([])
        line_no += 1

    for index in range(1, FIRST_BUILD_COL + widest + 1):
        letter = get_column_letter(index)
        ws.column_dimensions[letter].width = 16 if index < FIRST_BUILD_COL else 14
    ws.freeze_panes = ws.cell(3, FIRST_BUILD_COL + 1)


def build_chart_workbook(charts: Sequence[Chart], program: str = "",
                         phase: str = "") -> bytes:
    """The chart on its own, ready to hand to Circuit Health."""
    wb = Workbook()
    wb.remove(wb.active)
    write_chart_sheet(wb, charts, program, phase)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
