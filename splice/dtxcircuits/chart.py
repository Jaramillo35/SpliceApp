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
from splice.inline.pairing import mate_name
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

#: The readable sheet. ``SHEET`` (imported from splice.inline.summary) is the
#: blocked one Circuit Health parses; both are written, because flattening the
#: blocks would have quietly cost the round trip.
FLAT_SHEET = "Circuit Chart"

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
    #: where the wire goes. A wire has two ends; the chart is written one end
    #: per row, so without these the far end has to be found by eye.
    other_family: str = ""
    other_cnum: str = ""
    other_cavity: str = ""
    other_device: str = ""

    @property
    def end_type(self) -> str:
        if self.is_splice:
            return "Splice"
        return "Inline" if is_pass_through(self.cnum) else "Device"

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


def is_pass_through(cnum: str) -> bool:
    """Is this end an inline connector rather than a device?

    An inline is a joint between two harnesses, not a thing that gets fitted,
    so it has no applicability of its own — it carries whatever the circuit
    carries. In 2028RU X2_A, 1,924 of the 2,954 blank sales-code cells sit on
    inlines while 2,264 of the 2,458 stated ones sit on devices: the DTx
    states applicability at devices and leaves inlines blank.

    Recognised by the same X/Y naming ``splice.inline.pairing`` resolves
    mates with; the DTx has no device-type column to ask instead.
    """
    return mate_name(cnum) is not None


def _union(parts: Sequence[str]) -> Optional[str]:
    unique = sorted({f"({p})" for p in parts if p})
    return "/".join(unique) if unique else None


def flowed_conditions(rows: Sequence) -> Dict[str, Optional[str]]:
    """One condition per circuit, unioned over its device ends everywhere.

    The whole-circuit view, used where a harness states nothing of its own.
    ``None`` means unconditional, which no expression says.
    """
    stated: Dict[str, List[str]] = {}
    unconditional: set = set()
    for row in rows:
        circuit = getattr(row, "circuit", "")
        if not circuit:
            continue
        stated.setdefault(circuit, [])
        if is_pass_through(getattr(row, "cnum", "")):
            continue
        condition = conventions.effective_condition(getattr(row, "sales_code", ""))
        if condition is None:
            unconditional.add(circuit)
        else:
            stated[circuit].append(condition)
    return {circuit: (None if circuit in unconditional else _union(parts))
            for circuit, parts in stated.items()}


def harness_conditions(rows: Sequence) -> Dict[tuple, Optional[str]]:
    """``(circuit, family) -> condition``, reconciled per harness.

    A circuit does not have one applicability. It has one per harness, because
    what makes it present in a harness is the devices *that harness* connects
    it to. ``501`` on a ground stud in the IP is ground truth that the segment
    is always there; the same circuit reaching a HAH device in the HVAC is
    present only on HAH builds. Collapsing those to a single circuit-wide
    condition loses whichever one is narrower — 60 circuits in 2028RU X2_A
    have exactly that shape.

    So each harness is resolved from its own ends, in order of authority:

    1. **Its device ends.** One unconditional device end (blank, or a bare
       ``501``) makes the segment unconditional; otherwise the stated
       conditions are OR-ed, since any fitted device pulls the wire in.
    2. **Its inline ends that state something**, for a harness the circuit
       only passes through. Rare (194 rows) but decisive when present.
    3. **The circuit's conditions elsewhere.** A pure pass-through states
       nothing, and inheriting is better than calling it unconditional: in
       ``D442`` every device end reads ``SDE`` and only the DASH inlines are
       blank, so the DASH segment is ``SDE`` too, not "always".

    A blank on an inline never reaches any of these. It is silence, and
    reading it as "unconditional" is what made a whole circuit collapse.
    """
    device: Dict[tuple, List[str]] = {}
    inline: Dict[tuple, List[str]] = {}
    unconditional: set = set()
    keys: set = set()

    for row in rows:
        circuit = getattr(row, "circuit", "")
        family = getattr(row, "harness_family", "")
        if not circuit:
            continue
        key = (circuit, family)
        keys.add(key)
        condition = conventions.effective_condition(getattr(row, "sales_code", ""))
        if is_pass_through(getattr(row, "cnum", "")):
            if condition is not None:
                inline.setdefault(key, []).append(condition)
            continue
        if condition is None:
            unconditional.add(key)
        else:
            device.setdefault(key, []).append(condition)

    whole = flowed_conditions(rows)
    resolved: Dict[tuple, Optional[str]] = {}
    for key in keys:
        circuit, _family = key
        if key in unconditional:
            resolved[key] = None
        elif key in device:
            resolved[key] = _union(device[key])
        elif key in inline:
            resolved[key] = _union(inline[key])
        else:
            resolved[key] = whole.get(circuit)
    return resolved


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
    # Reconciled per harness, not once per circuit: a 501 ground in one
    # harness must not erase a HAH device in another.
    conditions = harness_conditions(rows)

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
                condition = conditions.get((row.circuit, entry.family))
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

    link_ends(charts, rows)
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
            branch = ChartRow(
                circuit=circuit, cnum=name,
                cavity=_int_to_alpha_suffix(index),
                device=f"SPLICE {name}",
                expression=end.expression,
                harness_expression=end.harness_expression,
                classification=end.classification,
                builds=list(end.builds), is_splice=True)
            # the two ends of one wire, each pointing at the other
            _join(end, chart.family, branch)
            _join(branch, chart.family, end)
            chart.rows.append(branch)


def _join(row: ChartRow, family: str, other: ChartRow) -> None:
    row.other_family = family
    row.other_cnum = other.cnum
    row.other_cavity = other.cavity
    row.other_device = other.device


def link_ends(charts: Sequence[Chart], rows: Sequence = ()) -> None:
    """Fill in the far end of every wire the splices did not already pair.

    A spliced circuit is settled when the splice is made: each branch runs
    device to splice, and both ends were joined then. What is left is the
    simple traffic:

    * an **inline** end continues at its mate — ``X301A`` at ``Y301A`` — which
      is how a circuit crosses a harness boundary, and is the one case where
      the far end is in a different family;
    * a circuit with exactly **two** unpaired ends joins them.

    Anything else is left blank on purpose. A circuit with three unpaired ends
    and no splice has no single far end, and inventing one would put a wire in
    the chart that nobody drew.

    ``rows`` is the DTx the charts were built from. It is consulted for one
    reason: the two-end shortcut has to count the circuit's ends in the
    *export*, not in the charts. A circuit reaching three harnesses of which
    only two are mapped would otherwise have its two charted ends joined to
    each other, drawing a wire that runs past the harness in between.
    """
    total_ends: Dict[str, set] = {}
    for row in rows:
        circuit = getattr(row, "circuit", "")
        if circuit:
            total_ends.setdefault(circuit, set()).add(
                (getattr(row, "cnum", ""), getattr(row, "pin", "")))
    by_circuit: Dict[str, List[tuple]] = {}
    for chart in charts:
        for row in chart.rows:
            by_circuit.setdefault(row.circuit, []).append((chart.family, row))

    for ends in by_circuit.values():
        open_ends = [(family, row) for family, row in ends if not row.other_cnum]
        located = {(family, row.cnum): (family, row) for family, row in ends}

        for family, row in list(open_ends):
            if row.other_cnum:
                continue
            mate = mate_name(row.cnum)
            if not mate:
                continue
            match = next(((f, r) for f, r in ends
                          if r.cnum.upper() == mate and not r.other_cnum), None)
            if match:
                other_family, other = match
                _join(row, other_family, other)
                _join(other, family, row)

        remaining = [(family, row) for family, row in ends if not row.other_cnum]
        circuit = ends[0][1].circuit
        known = total_ends.get(circuit)
        charted_all = known is None or len(known) == len(ends)
        if len(remaining) == 2 and charted_all:
            (family_a, a), (family_b, b) = remaining
            _join(a, family_b, b)
            _join(b, family_a, a)


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


#: The flat sheet's fixed columns, in reading order. Everything the DTx does
#: not state (wire size, material, colour) is left out rather than written as
#: an empty column — the blocked sheet has to carry them because the Circuit
#: Summary contract fixes their positions, but nothing here does.
FLAT_COLUMNS = [
    "Harness Family", "Harness", "Def Id", "Circuit", "End", "CNUM",
    "Cavity", "Connector PN", "Device",
    "Sales Code (DTx)", "Sales Code (this harness)", "Verdict",
    "Other End Harness", "Other End CNUM", "Other End Cavity",
    "Other End Device", "Builds Carrying",
]


def part_number_columns(charts: Sequence[Chart]) -> List[tuple]:
    """Every part number in the study, kept in harness order.

    One column each, grouped by the harness they belong to, so the matrix
    reads left to right the way the harnesses are listed. Returned as
    ``(harness, part number)`` because two harnesses can ship the same number
    and the header has to say which column is which.
    """
    columns: List[tuple] = []
    seen = set()
    for chart in charts:
        for part in chart.part_numbers:
            key = (chart.harness, part)
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def write_flat_sheet(wb: Workbook, charts: Sequence[Chart],
                     program: str = "", phase: str = "") -> None:
    """One table, one header row, one row per circuit end.

    The blocked sheet repeats a header for every harness because that is what
    the Circuit Summary parser keys on. It is the wrong shape to read or to
    filter: the repeated banners break sorting, and the fixed column positions
    force four columns the DTx cannot fill. This sheet is the same data as a
    plain table — title on row 1, the only header on row 2, and no column that
    is empty for every row.
    """
    ws = wb.create_sheet(FLAT_SHEET)
    ws.append(["Circuit Chart", " ".join(p for p in (program, phase) if p)])
    ws.cell(1, 1).font = _TITLE_FONT

    parts = part_number_columns(charts)
    header = list(FLAT_COLUMNS) + [part for _harness, part in parts]
    ws.append(header)
    for index in range(1, len(header) + 1):
        cell = ws.cell(2, index)
        cell.fill, cell.font = _BLOCK_FILL, _BLOCK_FONT
        cell.alignment = _BLOCK_ALIGN

    index_of = {key: len(FLAT_COLUMNS) + offset
                for offset, key in enumerate(parts)}
    line_no = 2
    for chart in charts:
        own = [(index_of[(chart.harness, part)], part)
               for part in chart.part_numbers]
        for row in chart.rows:
            line = [""] * len(header)
            line[0] = chart.family
            line[1] = chart.harness
            line[2] = chart.def_id
            line[3] = row.circuit
            line[4] = row.end_type
            line[5] = row.cnum
            line[6] = row.cavity
            line[7] = row.connector_pn
            line[8] = row.device
            line[9] = row.expression
            line[10] = row.harness_expression
            line[11] = row.classification
            line[12] = row.other_family
            line[13] = row.other_cnum
            line[14] = row.other_cavity
            line[15] = row.other_device
            line[16] = len(row.builds)
            carried = set(row.builds)
            for column, part in own:
                if part in carried:
                    line[column] = MARK
            ws.append(line)
            line_no += 1
            for column, part in own:
                if part in carried:
                    cell = ws.cell(line_no, column + 1)
                    cell.alignment, cell.font = _CENTER, _MARK_FONT
            if row.is_finding:
                for column in range(1, len(header) + 1):
                    ws.cell(line_no, column).fill = _NEVER_FILL

    widths = [18, 18, 9, 12, 9, 12, 8, 15, 22, 24, 24, 14, 18, 15, 9, 22, 10]
    for offset, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(offset)].width = width
    for offset in range(len(FLAT_COLUMNS) + 1, len(header) + 1):
        ws.column_dimensions[get_column_letter(offset)].width = 14
    ws.freeze_panes = ws.cell(3, 5)
    if line_no > 2:
        ws.auto_filter.ref = f"A2:{get_column_letter(len(header))}{line_no}"


def build_chart_workbook(charts: Sequence[Chart], program: str = "",
                         phase: str = "") -> bytes:
    """The chart on its own, ready to hand to Circuit Health."""
    wb = Workbook()
    wb.remove(wb.active)
    write_flat_sheet(wb, charts, program, phase)
    write_chart_sheet(wb, charts, program, phase)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
