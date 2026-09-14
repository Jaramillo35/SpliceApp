"""Set the Terminal Material of circuits in DEF Editor from an Excel list.

The engineer navigates DEF Editor by hand to Edit Harness → Circuits, where
every circuit of the harness is a row with a ``Term Matl`` cell that opens a
list (BERYLLIUM, GOLD, SILVER, SILVER+NICKEL, SILVER+TIN, TIN). They then
upload an Excel file with three columns — ``CNUM``, ``Circuit Name``,
``Terminal`` — and this sets each matching row's Term Matl.

This is the one thing in the kit that *changes* DEF Editor, so it is built as
preview, then apply, then report:

**Read circuits** extracts what the page shows — every row's ``Connector
No``, ``Circuit`` and ``Term Matl`` — and nothing else. That is the universe
the list is matched against: an Excel row whose circuit is not on this page
is *not on this page*, counted and kept for the CSV, and left out of the
preview, which shows only the circuits DEF Editor is showing.

**Preview** matches every Excel row to those circuits without touching
anything — CNUM against ``Connector No``, Circuit Name against ``Circuit``,
both exactly after trimming and case — and says per row what would happen:
*change* (with the current value), *already* that value, *not on this page*,
*several rows* (all of them will be set, and the count is shown), *no value*
(Terminal empty: left as it is), or *unknown value*.

**Apply** sets only the rows the preview said *change*, one at a time,
reading each cell back after setting it; a cell that reads back different is
reported as *failed*, not assumed.

Values are matched exactly, never guessed. The Excel may say Silver, Gold or
Tin (any case); those become SILVER, GOLD, TIN. Anything else — including
DEF Editor's own SILVER+NICKEL, which the source list does not use — is
reported and left alone, because a wrong plating written into a released
harness is worse than a row an engineer has to do by hand.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from defauto import ids
from defauto.backend import AutomationError, Backend, Grid

#: what the incoming Excel may say, and what DEF Editor calls it
INPUT_VALUES = {"SILVER": "SILVER", "GOLD": "GOLD", "TIN": "TIN"}

#: the Excel's columns, matched case-insensitively and trimmed
XLSX_COLUMNS = ("CNUM", "Circuit Name", "Terminal")

CHANGE = "change"
ALREADY = "already"
NOT_FOUND = "not found"
NO_VALUE = "no value"
UNKNOWN = "unknown value"
APPLIED = "applied"
FAILED = "failed"

STATUS_LABEL = {
    CHANGE: "Will change", ALREADY: "Already that value",
    NOT_FOUND: "Not on this page", NO_VALUE: "Terminal empty — left as is",
    UNKNOWN: "Unknown value — left as is", APPLIED: "Applied",
    FAILED: "Failed — read back different",
}


def normalise_terminal(value) -> Optional[str]:
    """``' silver '`` → ``SILVER``; empty → ``""``; anything else → None."""
    text = "" if value is None else str(value).strip().upper()
    if not text:
        return ""
    return INPUT_VALUES.get(text)


@dataclass
class Update:
    """One row of the Excel."""

    line: int                   # the Excel row number, for the report
    cnum: str
    circuit: str
    terminal: str               # as written


@dataclass
class Planned:
    update: Update
    status: str
    target: str = ""            # the DEF Editor value to set
    current: str = ""           # what the cell holds now
    rows: List[int] = field(default_factory=list)   # grid row indexes (0-based)
    detail: str = ""

    @property
    def will_change(self) -> bool:
        return self.status == CHANGE

    def as_row(self) -> dict:
        return {"Excel row": self.update.line, "CNUM": self.update.cnum,
                "Circuit": self.update.circuit, "Terminal": self.update.terminal,
                "Current": self.current, "Set to": self.target,
                "Rows": len(self.rows), "Status": STATUS_LABEL.get(self.status, self.status),
                "Detail": self.detail}


# ------------------------------------------------------------------ reading
def read_updates(data: bytes, name: str = "") -> List[Update]:
    """The Excel's rows. Column order does not matter; the three names do."""
    from openpyxl import load_workbook  # noqa: PLC0415 - only this reads Excel

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - said in the user's words
        raise AutomationError(f"{name or 'The file'} could not be opened as an "
                              f"Excel workbook: {exc}") from exc
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = next(rows, None)
    if header is None:
        raise AutomationError(f"{name or 'The file'} is empty")
    labels = ["" if h is None else str(h).strip().lower() for h in header]
    where = {}
    for wanted in XLSX_COLUMNS:
        try:
            where[wanted] = labels.index(wanted.lower())
        except ValueError:
            raise AutomationError(
                f"{name or 'The file'} has no {wanted!r} column. It needs "
                f"{', '.join(XLSX_COLUMNS)} in its first row; it has "
                f"{', '.join(l for l in labels if l) or 'nothing'}.") from None
    out: List[Update] = []
    for line, values in enumerate(rows, start=2):
        cell = lambda key: (  # noqa: E731
            "" if values[where[key]] is None else str(values[where[key]]).strip())
        if not any(v not in (None, "") for v in values):
            continue
        out.append(Update(line, cell("CNUM"), cell("Circuit Name"), cell("Terminal")))
    if not out:
        raise AutomationError(f"{name or 'The file'} has a header and no rows")
    return out


# ---------------------------------------------------------------- planning
def _column(grid: Grid, wanted: str) -> int:
    """Index of a grid column by its header, tolerant of case and spacing."""
    key = wanted.strip().lower().replace(" ", "")
    for i, header in enumerate(grid.headers):
        if header.strip().lower().replace(" ", "") == key:
            return i
    raise AutomationError(
        f"The circuits grid has no {wanted!r} column — its headers are: "
        f"{', '.join(grid.headers) or 'none read'}. Is DEF Editor on the "
        "Edit Harness → Circuits page?")


def _key(cnum: str, circuit: str) -> tuple:
    return cnum.strip().upper(), circuit.strip().upper()


@dataclass
class Circuit:
    """One row of the page, as the updater sees it."""

    row: int                    # grid row index (0-based)
    cnum: str
    circuit: str
    terminal: str               # the Term Matl cell as it reads now


@dataclass
class Circuits:
    """What the Circuits page shows: the universe the list is matched in."""

    grid: Grid
    cnum_i: int
    ckt_i: int
    term_i: int

    def __len__(self) -> int:
        return len(self.grid.rows)

    def rows(self) -> List[Circuit]:
        return [Circuit(r, row[self.cnum_i], row[self.ckt_i], row[self.term_i])
                for r, row in enumerate(self.grid.rows)
                if max(self.cnum_i, self.ckt_i, self.term_i) < len(row)]

    def index(self) -> dict:
        """``(CNUM, circuit) → [row indexes]``."""
        out: dict = {}
        for c in self.rows():
            out.setdefault(_key(c.cnum, c.circuit), []).append(c.row)
        return out

    def terminal(self, row: int) -> str:
        return self.grid.rows[row][self.term_i].strip()

    def set_terminal(self, row: int, value: str) -> None:
        """Keep the extracted copy in step with a cell that was written."""
        self.grid.rows[row][self.term_i] = value


def read_circuits(backend: Backend,
                  progress: Optional[Callable[[int, int], None]] = None) -> Circuits:
    """Extract the circuits DEF Editor is showing, touching nothing.

    Reads only the three columns the updater matches on: on DEF Editor's
    grid every cell is a cross-process call, and 785 rows × 20 columns is a
    wait that looks like a hang; 785 × 3 is a few seconds.
    """
    grid = backend.grid(ids.GRID_CIRCUITS,
                        columns=[ids.TERM_COLUMNS["cnum"], ids.TERM_COLUMNS["circuit"],
                                 ids.TERM_COLUMNS["terminal"]],
                        progress=progress)
    return Circuits(grid, _column(grid, ids.TERM_COLUMNS["cnum"]),
                    _column(grid, ids.TERM_COLUMNS["circuit"]),
                    _column(grid, ids.TERM_COLUMNS["terminal"]))


def _why_not(u: Update, circuits: Circuits) -> str:
    """For a row that is not on the page: what the page has that is close."""
    cnum, ckt = _key(u.cnum, u.circuit)
    at = sorted({c.cnum for c in circuits.rows() if _key("", c.circuit)[1] == ckt})
    if at:
        return f"circuit {u.circuit} is on this page under {', '.join(at)}, not {u.cnum}"
    if any(_key(c.cnum, "")[0] == cnum for c in circuits.rows()):
        return f"{u.cnum} is on this page but has no circuit {u.circuit}"
    return "neither this CNUM nor this circuit is on this page"


def plan(backend: Backend, updates: Sequence[Update],
         progress: Optional[Callable[[int, int], None]] = None,
         circuits: Optional[Circuits] = None) -> List[Planned]:
    """Match every Excel row to the circuits on the page, touching nothing.

    ``circuits`` is what ``read_circuits`` extracted; when it is not given
    the page is read here. Rows the page does not show come back as
    *not on this page* with a hint at what the page has instead — they are
    kept, for the CSV, and ``on_page`` leaves them out of the preview.
    """
    if circuits is None:
        circuits = read_circuits(backend, progress)
    grid, term_i = circuits.grid, circuits.term_i
    index = circuits.index()

    out: List[Planned] = []
    for u in updates:
        target = normalise_terminal(u.terminal)
        rows = index.get(_key(u.cnum, u.circuit), [])
        current = sorted({grid.rows[r][term_i].strip() for r in rows}) if rows else []
        shown = " / ".join(v or "(empty)" for v in current)
        if not rows:
            out.append(Planned(u, NOT_FOUND, target or "", "", [], _why_not(u, circuits)))
        elif target is None:
            out.append(Planned(u, UNKNOWN, "", shown, rows,
                               f"{u.terminal!r} is not Silver, Gold or Tin"))
        elif target == "":
            out.append(Planned(u, NO_VALUE, "", shown, rows))
        elif all(v.upper() == target for v in current):
            out.append(Planned(u, ALREADY, target, shown, rows))
        else:
            detail = f"{len(rows)} rows share this CNUM and circuit — all will be set" \
                if len(rows) > 1 else ""
            out.append(Planned(u, CHANGE, target, shown, rows, detail))
    return out


def on_page(planned: Sequence[Planned]) -> List[Planned]:
    """The rows the page shows — what the preview lists."""
    return [p for p in planned if p.status != NOT_FOUND]


def summary(planned: Sequence[Planned]) -> dict:
    out = {s: 0 for s in STATUS_LABEL}
    for p in planned:
        out[p.status] = out.get(p.status, 0) + 1
    return out


# ----------------------------------------------------------------- applying
def apply(backend: Backend, planned: Sequence[Planned],
          on_row: Optional[Callable[[Planned], None]] = None,
          circuits: Optional[Circuits] = None) -> List[Planned]:
    """Set every row the preview said *change*, reading each back.

    Rows the preview did not mark as a change are never touched — a preview
    is a promise about what apply will do, and apply keeps it.
    """
    term = ids.TERM_COLUMNS["terminal"]
    for p in planned:
        if not p.will_change:
            continue
        failures = []
        for r in p.rows:
            try:
                backend.set_cell(ids.GRID_CIRCUITS, r, term, p.target)
            except AutomationError as exc:
                failures.append(f"row {r + 1}: {exc}")
                continue
        # read back the cells written, not the whole grid again
        read_back = []
        for r in p.rows:
            try:
                read_back.append(backend.cell(ids.GRID_CIRCUITS, r, term).strip())
            except AutomationError as exc:
                read_back.append(f"?({exc})")
        wrong = [v for v in read_back if v.upper() != p.target]
        if failures or wrong:
            p.status = FAILED
            p.detail = "; ".join(failures + [f"reads back {v or '(empty)'!r}" for v in wrong])
        else:
            p.status = APPLIED
            p.current = p.target
        if circuits is not None:
            for r, v in zip(p.rows, read_back):
                if not v.startswith("?("):
                    circuits.set_terminal(r, v)
        if on_row is not None:
            on_row(p)
    return list(planned)


def results_csv(planned: Sequence[Planned]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(planned[0].as_row()) if planned else
                            ["Excel row", "CNUM", "Circuit", "Terminal", "Current",
                             "Set to", "Rows", "Status", "Detail"],
                            lineterminator="\n")
    writer.writeheader()
    for p in planned:
        writer.writerow(p.as_row())
    return buf.getvalue()
