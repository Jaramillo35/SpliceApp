"""The DTCR Matching Report library: upload once, reuse everywhere.

A DTCR Matching Report describes one *scope* — a program, a model year and an
engineering phase. Every SECR generated in that scope enriches against the same
report, so re-attaching the file to each generation was pure repetition and an
invitation to enrich two SECRs of the same scope from two different reports.

Here a report is stored once against its scope. Generation looks it up; the
dashboard reads it. Re-uploading a scope replaces it, because two reports
disagreeing about the same program/year/phase is a contradiction, not history.

Three things are persisted together:

``dtcr_report``         the scope, the provenance, and the original workbook
``dtcr_report_row``     one row per DTCR, parsed into columns
``dtcr_report_family``  the harness families exploded out of those rows

The original bytes are kept because enrichment consumes the workbook itself;
the parsed rows exist because a dashboard cannot chart a BLOB.
"""

from __future__ import annotations

import getpass
import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from secrdb.core.common.errors import SpliceInputError
from secrdb.core.common.logging import get_logger
from secrdb.core.secr import db as secr_db

logger = get_logger(__name__)

#: Source column -> stored column. The report is produced by SECR Management,
#: so the names are stable; anything missing is stored empty rather than
#: rejected, because a partial report is still worth having.
_COLUMNS = {
    "DTCR#": "dtcr_number",
    "Device Transmittal": "device_transmittal",
    "Extracted Device Control Number": "device_control_number",
    "Reason for change": "reason_for_change",
    "Status": "status",
    "Bulletin": "bulletin",
    "Match Method": "match_method",
    "Matched DTx Value": "matched_dtx_value",
    "CNUM": "cnum",
    "Harness Family": "harness_family",
}

#: Match methods that mean the DTCR was never tied to a harness family.
UNMATCHED_METHODS = {"NO MATCH", "NOMATCH", ""}

_SCOPE_RE = re.compile(
    r"(?P<my>\d{2})(?P<program>[A-Z]{2,4})[_\- ]+(?P<phase>X\d[A-Z]?)",
    re.IGNORECASE,
)
_VS_RE = re.compile(r"X\d[A-Z]?", re.IGNORECASE)


@dataclass
class ReportScope:
    """Which program, model year and phase a report belongs to."""

    program: str = ""
    model_year: str = ""
    phase: str = ""

    @property
    def is_complete(self) -> bool:
        return bool(self.program and self.model_year and self.phase)

    def __str__(self) -> str:
        return f"MY{self.model_year} · {self.program} · {self.phase}"


@dataclass
class ReportStatistics:
    """Everything the dashboard draws, computed once from the stored rows."""

    report: Dict[str, Any] = field(default_factory=dict)
    total: int = 0
    with_cnum: int = 0
    with_harness: int = 0
    with_bulletin: int = 0
    unmatched: int = 0
    multi_family: int = 0
    by_status: List[Dict[str, Any]] = field(default_factory=list)
    by_match_method: List[Dict[str, Any]] = field(default_factory=list)
    by_harness_family: List[Dict[str, Any]] = field(default_factory=list)
    by_bulletin: List[Dict[str, Any]] = field(default_factory=list)
    unmatched_rows: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def matched(self) -> int:
        return self.total - self.unmatched

    @property
    def match_rate(self) -> float:
        return (self.matched / self.total * 100) if self.total else 0.0

    @property
    def cnum_rate(self) -> float:
        return (self.with_cnum / self.total * 100) if self.total else 0.0


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------

def normalize_scope(
    program: str = "", model_year: str = "", phase: str = ""
) -> ReportScope:
    """Upper-case, trimmed, and the model year reduced to two digits.

    ``2028`` and ``28`` name the same year; storing both would split one scope
    into two and make a report unfindable from the other spelling.
    """
    year = re.sub(r"\D", "", str(model_year or ""))
    if len(year) == 4:
        year = year[2:]
    return ReportScope(
        program=str(program or "").strip().upper(),
        model_year=year,
        phase=str(phase or "").strip().upper(),
    )


def parse_scope_from_filename(filename: str) -> ReportScope:
    """Best-effort scope from a name like ``DTCR_Matching_Report_28RU_X1_vs_X2``.

    A report built from a phase compare names both phases. The scope taken is
    the **later** one, matching how a SECR is scoped to its NEW DEF — the
    report describes where the design is going, not where it came from. It is
    only a default: the caller confirms it before anything is stored.
    """
    stem = Path(str(filename or "")).stem
    match = _SCOPE_RE.search(stem)
    if not match:
        return ReportScope()
    phases = _VS_RE.findall(stem[match.start("phase"):])
    phase = phases[-1] if phases else match.group("phase")
    return normalize_scope(
        program=match.group("program"),
        model_year=match.group("my"),
        phase=phase,
    )


def split_families(value: Any) -> List[str]:
    """``"BODY_RIGHT, BODY_LEFT"`` -> ``["BODY_RIGHT", "BODY_LEFT"]``.

    One cell can name several harness families. Upper-cased because the report
    mixes conventions (``Seat_Back_Pass_2`` beside ``SEAT_3RD_ROW_LEFT``) and
    two spellings of one family must not become two bars on a chart.
    """
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"nan", "none"}:
        return []
    parts = [p.strip().upper() for p in re.split(r"[,;/]+", raw)]
    seen: List[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return seen


# ---------------------------------------------------------------------------
# Storing
# ---------------------------------------------------------------------------

def _text(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def read_report(payload: bytes) -> pd.DataFrame:
    """Parse the workbook into the canonical columns. Raises if unusable."""
    if not payload:
        raise SpliceInputError("The DTCR Matching Report is empty.")
    try:
        frame = pd.read_excel(io.BytesIO(payload), dtype=str)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user
        raise SpliceInputError(
            f"Could not read the DTCR Matching Report: {exc}"
        ) from exc

    frame.columns = [str(c).strip() for c in frame.columns]
    if "DTCR#" not in frame.columns:
        raise SpliceInputError(
            "This does not look like a DTCR Matching Report — no 'DTCR#' "
            "column. Expected the sheet exported by SECR Management → "
            "DTCR Matching."
        )
    frame = frame.dropna(subset=["DTCR#"])
    for source in _COLUMNS:
        if source not in frame.columns:
            frame[source] = ""
    return frame.reset_index(drop=True)


def save_report(
    payload: bytes,
    filename: str,
    *,
    program: str,
    model_year: str,
    phase: str,
    note: str = "",
    db_path: Optional[Path] = None,
) -> int:
    """Store a report against its scope, replacing any report already there."""
    scope = normalize_scope(program, model_year, phase)
    if not scope.is_complete:
        raise SpliceInputError(
            "Program, Model Year and Phase are all required to file a DTCR "
            "Matching Report — they are how it is found again."
        )
    frame = read_report(payload)
    records = [
        {stored: _text(row.get(source)) for source, stored in _COLUMNS.items()}
        for _index, row in frame.iterrows()
    ]
    records = [r for r in records if r["dtcr_number"]]
    if not records:
        raise SpliceInputError("The report has no DTCR rows.")

    secr_db.init_db(db_path)
    with secr_db.connect(db_path) as conn:
        conn.execute(
            "DELETE FROM dtcr_report WHERE program = ? AND model_year = ?"
            " AND phase = ?",
            (scope.program, scope.model_year, scope.phase),
        )
        cursor = conn.execute(
            """
            INSERT INTO dtcr_report (
                program, model_year, phase, filename, sha256, size_bytes,
                row_count, content, uploaded_by, note
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                scope.program,
                scope.model_year,
                scope.phase,
                filename or "DTCR_Matching_Report.xlsx",
                hashlib.sha256(payload).hexdigest(),
                len(payload),
                len(records),
                payload,
                _current_user(),
                note,
            ),
        )
        report_id = int(cursor.lastrowid)
        for record in records:
            row_cursor = conn.execute(
                """
                INSERT INTO dtcr_report_row (
                    report_id, dtcr_number, device_transmittal,
                    device_control_number, reason_for_change, status, bulletin,
                    match_method, matched_dtx_value, cnum, harness_family
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    report_id,
                    record["dtcr_number"],
                    record["device_transmittal"],
                    record["device_control_number"],
                    record["reason_for_change"],
                    record["status"],
                    record["bulletin"],
                    record["match_method"],
                    record["matched_dtx_value"],
                    record["cnum"],
                    record["harness_family"],
                ),
            )
            row_id = int(row_cursor.lastrowid)
            for family in split_families(record["harness_family"]):
                conn.execute(
                    "INSERT INTO dtcr_report_family"
                    " (report_id, row_id, dtcr_number, harness_family)"
                    " VALUES (?,?,?,?)",
                    (report_id, row_id, record["dtcr_number"], family),
                )
    logger.info(
        "Stored DTCR Matching Report %s (%s rows) for %s",
        filename, len(records), scope,
    )
    return report_id


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - a missing username is not an error
        return ""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

_REPORT_COLUMNS = (
    "id, program, model_year, phase, filename, sha256, size_bytes, row_count,"
    " uploaded_at, uploaded_by, note"
)


def list_reports(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every stored report, newest first. Never returns the workbook bytes."""
    secr_db.init_db(db_path)
    with secr_db.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {_REPORT_COLUMNS} FROM dtcr_report"
            " ORDER BY model_year DESC, program, phase"
        ).fetchall()
    return [dict(row) for row in rows]


def get_report(
    report_id: int, db_path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    secr_db.init_db(db_path)
    with secr_db.connect(db_path) as conn:
        row = conn.execute(
            f"SELECT {_REPORT_COLUMNS} FROM dtcr_report WHERE id = ?",
            (report_id,),
        ).fetchone()
    return dict(row) if row else None


def find_report_for_scope(
    program: str, model_year: str, phase: str, db_path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """The report filed for a scope, or ``None``. Used by generation."""
    scope = normalize_scope(program, model_year, phase)
    if not scope.is_complete:
        return None
    secr_db.init_db(db_path)
    with secr_db.connect(db_path) as conn:
        row = conn.execute(
            f"SELECT {_REPORT_COLUMNS} FROM dtcr_report"
            " WHERE program = ? AND model_year = ? AND phase = ?",
            (scope.program, scope.model_year, scope.phase),
        ).fetchone()
    return dict(row) if row else None


def report_bytes(
    report_id: int, db_path: Optional[Path] = None
) -> Optional[bytes]:
    """The original workbook, for enrichment to consume."""
    secr_db.init_db(db_path)
    with secr_db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT content FROM dtcr_report WHERE id = ?", (report_id,)
        ).fetchone()
    return bytes(row["content"]) if row and row["content"] else None


def report_rows(
    report_id: int, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    secr_db.init_db(db_path)
    with secr_db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM dtcr_report_row WHERE report_id = ?"
            " ORDER BY dtcr_number",
            (report_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_report(report_id: int, db_path: Optional[Path] = None) -> bool:
    secr_db.init_db(db_path)
    with secr_db.connect(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM dtcr_report WHERE id = ?", (report_id,)
        )
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _counts(conn, sql: str, report_id: int, label: str) -> List[Dict[str, Any]]:
    return [
        {label: row[0] or "(none)", "count": row[1]}
        for row in conn.execute(sql, (report_id,)).fetchall()
    ]


def report_statistics(
    report_id: int, db_path: Optional[Path] = None
) -> ReportStatistics:
    """Aggregate one report into everything the dashboard shows.

    Counted in SQL rather than in the page, so the numbers beside a chart and
    the bars in it come from the same query and cannot drift apart.
    """
    stats = ReportStatistics()
    report = get_report(report_id, db_path=db_path)
    if report is None:
        return stats
    stats.report = report

    secr_db.init_db(db_path)
    with secr_db.connect(db_path) as conn:
        stats.total = conn.execute(
            "SELECT COUNT(*) FROM dtcr_report_row WHERE report_id = ?",
            (report_id,),
        ).fetchone()[0]
        stats.with_cnum = conn.execute(
            "SELECT COUNT(*) FROM dtcr_report_row"
            " WHERE report_id = ? AND cnum != ''",
            (report_id,),
        ).fetchone()[0]
        stats.with_harness = conn.execute(
            "SELECT COUNT(*) FROM dtcr_report_row"
            " WHERE report_id = ? AND harness_family != ''",
            (report_id,),
        ).fetchone()[0]
        stats.with_bulletin = conn.execute(
            "SELECT COUNT(*) FROM dtcr_report_row"
            " WHERE report_id = ? AND bulletin != ''",
            (report_id,),
        ).fetchone()[0]
        # Unmatched means "no harness family", not "the automatic method said
        # No Match". A DTCR can be reported as No Match and still carry its
        # families, resolved another way — counting it as a gap would send an
        # engineer looking for a problem that is already solved.
        stats.unmatched = conn.execute(
            "SELECT COUNT(*) FROM dtcr_report_row"
            " WHERE report_id = ? AND harness_family = ''",
            (report_id,),
        ).fetchone()[0]
        stats.multi_family = conn.execute(
            "SELECT COUNT(*) FROM (SELECT dtcr_number FROM dtcr_report_family"
            " WHERE report_id = ? GROUP BY dtcr_number HAVING COUNT(*) > 1)",
            (report_id,),
        ).fetchone()[0]

        stats.by_status = _counts(
            conn,
            "SELECT status, COUNT(*) FROM dtcr_report_row WHERE report_id = ?"
            " GROUP BY status ORDER BY COUNT(*) DESC",
            report_id,
            "status",
        )
        stats.by_match_method = _counts(
            conn,
            "SELECT match_method, COUNT(*) FROM dtcr_report_row"
            " WHERE report_id = ? GROUP BY match_method ORDER BY COUNT(*) DESC",
            report_id,
            "match_method",
        )
        stats.by_harness_family = _counts(
            conn,
            "SELECT harness_family, COUNT(DISTINCT dtcr_number)"
            " FROM dtcr_report_family WHERE report_id = ?"
            " GROUP BY harness_family ORDER BY COUNT(DISTINCT dtcr_number) DESC",
            report_id,
            "harness_family",
        )
        stats.by_bulletin = _counts(
            conn,
            "SELECT bulletin, COUNT(*) FROM dtcr_report_row"
            " WHERE report_id = ? AND bulletin != ''"
            " GROUP BY bulletin ORDER BY COUNT(*) DESC",
            report_id,
            "bulletin",
        )
        stats.unmatched_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT dtcr_number, device_transmittal, status, match_method,"
                "       cnum, reason_for_change"
                " FROM dtcr_report_row WHERE report_id = ?"
                "   AND harness_family = ''"
                " ORDER BY dtcr_number",
                (report_id,),
            ).fetchall()
        ]
    return stats
