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
from typing import Dict, Iterable, List, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from splice.dtxcircuits.models import NEVER
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
    expression: str = ""
    classification: str = ""
    builds: List[str] = field(default_factory=list)

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


def build_charts(entries: Iterable, rows: Sequence) -> List[Chart]:
    """One chart per family × harness pairing, from the resolved analysis.

    ``rows`` are the DTx circuit rows the analysis was run on — the repaired
    ones, so the chart shows what was actually resolved rather than what the
    export said before the SE fixed it.
    """
    by_family: Dict[str, List] = {}
    for row in rows:
        by_family.setdefault(getattr(row, "harness_family", ""), []).append(row)

    charts: List[Chart] = []
    for entry in entries:
        analysis = entry.analysis
        applicability = {c.circuit: c for c in analysis.circuits}
        connector_pn = {}
        for row in by_family.get(entry.family, []):
            if row.cnum and row.cnum not in connector_pn:
                connector_pn[row.cnum] = row.connector_pn or ""

        chart = Chart(
            family=entry.family, harness=analysis.harness,
            def_id=analysis.def_id,
            part_numbers=[b.part_number for b in getattr(analysis, "builds_list", [])]
            or _part_numbers(analysis),
        )

        seen = set()
        for row in by_family.get(entry.family, []):
            key = (row.circuit, row.cnum, row.pin)
            if not row.circuit or key in seen:
                continue
            seen.add(key)
            item = applicability.get(row.circuit)
            chart.rows.append(ChartRow(
                circuit=row.circuit, cnum=row.cnum, cavity=row.pin,
                device=row.function or "",
                connector_pn=connector_pn.get(row.cnum, ""),
                expression=(item.expression or "") if item else (row.sales_code or ""),
                classification=item.classification if item else "",
                # A circuit end is carried by exactly the builds that carry its
                # circuit: applicability is resolved per circuit, and a cavity
                # cannot be present on a build the wire is absent from.
                builds=list(item.builds_with) if item else [],
            ))
        chart.rows.sort(key=lambda r: (r.circuit, r.cnum, _cavity_key(r.cavity)))
        charts.append(chart)

    logger.info("Built %d circuit chart(s), %d row(s)",
                len(charts), sum(len(c.rows) for c in charts))
    return charts


def _part_numbers(analysis) -> List[str]:
    """Every part number the analysis mentions, in a stable order.

    Taken from the circuits rather than the harness so a chart can be built
    from an analysis alone; a build that carries nothing still appears,
    because an empty column is itself the finding.
    """
    ordered: List[str] = []
    for circuit in analysis.circuits:
        for part in list(circuit.builds_with) + list(circuit.builds_without):
            if part not in ordered:
                ordered.append(part)
    return sorted(ordered)


def _cavity_key(value: str):
    """Sort cavities numerically where they are numbers, else alphabetically."""
    text = (value or "").strip()
    head = text.split(":")[0]
    return (0, int(head), text) if head.isdigit() else (1, 0, text)


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
            line[COL_SALES_CODE] = row.expression
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
