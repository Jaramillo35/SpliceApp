"""Read circuits out of a Detailed DTx Circuits Report.

The export carries a title block above the real header, and states its own
programme and build phase in that block — which is the only trustworthy
source, since filenames disagree with contents often enough to matter.
"""

from __future__ import annotations

import io
import logging
import re
from typing import List, Tuple

import pandas as pd

from splice.common.errors import SpliceError
from splice.dtxcircuits.models import CircuitRow, DtxMeta

logger = logging.getLogger(__name__)

#: Columns the analysis needs; the rest of the export is carried past.
REQUIRED = ("Harness Family", "Circuit Name")
SALES_CODE = "Sales Code"

_PROGRAM = re.compile(r"Vehicle Program\s*[-:]\s*(\S+)", re.I)
_PHASE = re.compile(r"Build Phase\s*[-:]\s*(\S+)", re.I)
_DATE = re.compile(r"Report Date\s*[-:]\s*([^\n]+)", re.I)

MAX_HEADER_SCAN = 25  # the title block is a handful of rows, never dozens


def _find_header_row(raw: pd.DataFrame) -> int:
    """Row index holding the column names (the export pads a title block above)."""
    for i in range(min(MAX_HEADER_SCAN, len(raw))):
        values = {str(v).strip() for v in raw.iloc[i].tolist()}
        if all(col in values for col in REQUIRED):
            return i
    raise SpliceError(
        "This does not look like a Detailed DTx Circuits Report: no header row "
        f"with {' and '.join(REQUIRED)} in the first {MAX_HEADER_SCAN} rows.")


def _meta_from_title_block(raw: pd.DataFrame, header_row: int) -> DtxMeta:
    text = "\n".join(
        " ".join(str(v) for v in raw.iloc[i].tolist() if str(v) != "nan")
        for i in range(header_row)
    )
    meta = DtxMeta()
    for pattern, field in ((_PROGRAM, "program"), (_PHASE, "phase"), (_DATE, "report_date")):
        match = pattern.search(text)
        if match:
            setattr(meta, field, match.group(1).strip())
    return meta


def read_dtx_meta(payload, filename: str = "",
                  sheet: str | None = None) -> DtxMeta:
    """Just the title block — programme, build phase, report date.

    Reading only the first rows of the first sheet, so a caller that wants to
    label a report does not pay for parsing tens of thousands of circuit rows.
    Returns an empty DtxMeta rather than raising: a caller that only wants a
    label should not fail because a file is unusual.
    """
    try:
        source = io.BytesIO(payload) if isinstance(payload, (bytes, bytearray)) else payload
        # only the first sheet, and only enough rows to hold a title block
        raw = pd.read_excel(source, sheet_name=sheet or 0, header=None,
                            dtype=str, nrows=MAX_HEADER_SCAN)
        try:
            header_row = _find_header_row(raw)
        except SpliceError:
            header_row = min(MAX_HEADER_SCAN, len(raw))
        return _meta_from_title_block(raw, header_row)
    except Exception as exc:  # noqa: BLE001 - a label must never break a report
        logger.info("Could not read a title block from %s: %s", filename, exc)
        return DtxMeta()


def read_dtx_circuits(payload, filename: str = "",
                      sheet: str | None = None) -> Tuple[List[CircuitRow], DtxMeta]:
    """Parse a DTx export into circuit rows plus the report's own metadata.

    Only the first sheet is read — it is the detail report, and it carries the
    title block stating the vehicle programme and build phase. Pass ``sheet``
    to override. Programme and phase always come from the file's contents,
    never from its name.
    """
    source = io.BytesIO(payload) if isinstance(payload, (bytes, bytearray)) else payload
    try:
        book = pd.read_excel(source, sheet_name=None, header=None, dtype=str)
    except Exception as exc:
        raise SpliceError(f"Could not read {filename or 'the DTx export'}: {exc}") from exc

    # The FIRST sheet is the detail report and the only one read: later sheets
    # (the Duplicate DTx Report) repeat rows under the same headers, and
    # counting them twice would double every circuit's occurrences.
    candidates = [sheet] if sheet else list(book)[:1]
    last_error = None
    for name in candidates:
        raw = book.get(name)
        if raw is None or raw.empty:
            continue
        try:
            header_row = _find_header_row(raw)
        except SpliceError as exc:
            last_error = exc
            continue
        meta = _meta_from_title_block(raw, header_row)
        frame = raw.iloc[header_row + 1:].copy()
        frame.columns = [str(v).strip() for v in raw.iloc[header_row].tolist()]
        frame = frame.dropna(how="all")

        def column(label: str):
            return frame[label] if label in frame.columns else pd.Series([""] * len(frame))

        rows: List[CircuitRow] = []
        for family, circuit, code, cnum, pin, connector, function in zip(
                column("Harness Family"), column("Circuit Name"),
                column(SALES_CODE), column("CNUM"), column("Pin Number"),
                column("Connector PN"), column("Circuit Function")):
            family = str(family or "").strip()
            circuit = str(circuit or "").strip()
            if not family or not circuit or family == "nan" or circuit == "nan":
                continue
            code = "" if str(code) in ("nan", "None") else str(code or "").strip()
            rows.append(CircuitRow(
                harness_family=family, circuit=circuit, sales_code=code,
                cnum=_clean(cnum), pin=_clean(pin),
                connector_pn=_clean(connector), function=_clean(function)))
        if not rows:
            continue
        meta.rows = len(rows)
        meta.families = len({r.harness_family for r in rows})
        logger.info("DTx %s: %d circuit rows, %d families, program=%s phase=%s",
                    filename, meta.rows, meta.families, meta.program, meta.phase)
        return rows, meta

    raise last_error or SpliceError(
        f"{filename or 'The DTx export'} has no readable circuit table.")


def _clean(value) -> str:
    text = str(value or "").strip()
    return "" if text in ("nan", "None") else text
