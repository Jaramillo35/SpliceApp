"""SECR database — SQLite persistence for generated SECR workbooks.

This is the only module that touches the database. It is called from app.py
after `create_secr_bytes()` / `update_secr_bytes()` succeed:

    record = secr_db.record_from_workbook(secr_bytes, action="create", ...)
    secr_id = secr_db.save_secr(record)

Design doc: docs/SECR_DATABASE_DESIGN.md
"""
from __future__ import annotations

import getpass
import io
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import openpyxl

from splice.config import SECR_DB_PATH as DB_PATH
from splice.secr.enrich import filter_dtcr_mapping_for_family
from splice.secr.identity import FIRST_SEQUENCE_NUMBER, scope_key
from splice.secr.parse import ParsedSecr, parse_secr_bytes

SCHEMA_VERSION = 3

#: v3 adds generated-SECR identity: a per (model year + phase) number sequence,
#: the structured identity columns, and generation provenance. Additive.
_MIGRATION_V3 = """
CREATE TABLE IF NOT EXISTS secr_sequence (
    model_year  TEXT NOT NULL,
    phase       TEXT NOT NULL,
    next_number INTEGER NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (model_year, phase)
);

-- Identity of a GENERATED SECR: model year + phase + sequence number + version.
-- Partial, so imported SECRs (no sequence number) are unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS ux_secr_generated_identity
    ON secr (scope_model_year, scope_phase, secr_sequence_number, version)
    WHERE secr_sequence_number IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_secr_scope
    ON secr (scope_model_year, scope_phase);
"""

# Columns added to `secr` in v3. The scope columns are normalized (2-digit model
# year, phase without its revision letter) so the numbering scope is unambiguous.
_V3_SECR_COLUMNS = {
    "secr_sequence_number": "INTEGER",
    "scope_model_year": "TEXT",
    "scope_phase": "TEXT",
    "version_number": "INTEGER",
    "generation_date": "TEXT",
    "old_def_source": "TEXT",
    "new_def_source": "TEXT",
    "metadata_provenance": "TEXT",
}

#: `import_origin` doubles as the spec's `origin_type`; rather than add a second
#: column meaning the same thing, these are its two values.
ORIGIN_GENERATED = "generated"
ORIGIN_IMPORTED = "imported"

#: v2 adds the change table (one row per changed field), source-file
#: provenance, and an audit trail. Applied additively to a v1 database — the
#: v1 tables and their rows are untouched.
_MIGRATION_V2 = """
CREATE TABLE IF NOT EXISTS secr_change (
    id            INTEGER PRIMARY KEY,
    secr_id       INTEGER NOT NULL REFERENCES secr(id) ON DELETE CASCADE,
    object_type   TEXT NOT NULL,
    object_id     TEXT NOT NULL,
    action        TEXT NOT NULL,
    field         TEXT,
    old_value     TEXT,
    new_value     TEXT,
    dtcr_number   TEXT,
    harness_pn    TEXT,
    sales_code    TEXT,
    se_comment    TEXT,
    source_sheet  TEXT NOT NULL,
    source_row    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS secr_source_file (
    secr_id     INTEGER PRIMARY KEY REFERENCES secr(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    content     BLOB,
    stored_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS secr_audit (
    id          INTEGER PRIMARY KEY,
    secr_number TEXT NOT NULL,
    version     TEXT,
    event       TEXT NOT NULL,
    detail      TEXT,
    at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    by_user     TEXT
);

CREATE INDEX IF NOT EXISTS ix_change_object ON secr_change (object_type, object_id);
CREATE INDEX IF NOT EXISTS ix_change_dtcr   ON secr_change (dtcr_number);
CREATE INDEX IF NOT EXISTS ix_change_secr   ON secr_change (secr_id);
CREATE INDEX IF NOT EXISTS ix_source_sha    ON secr_source_file (sha256);
CREATE INDEX IF NOT EXISTS ix_audit_secr    ON secr_audit (secr_number);
"""

# Columns added to the existing `secr` table in v2. ALTER TABLE ADD COLUMN is
# the only schema change SQLite applies in place, so each is listed separately
# and applied only when absent.
_V2_SECR_COLUMNS = {
    "import_origin": "TEXT NOT NULL DEFAULT 'generated'",
    "imported_at": "TEXT",
    "source_sha256": "TEXT",
    "parse_warnings": "TEXT",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS secr (
    id                   INTEGER PRIMARY KEY,
    secr_number          TEXT NOT NULL,
    version              TEXT NOT NULL DEFAULT 'A',
    filename             TEXT,
    action               TEXT NOT NULL CHECK (action IN ('create','update')),
    parent_secr_id       INTEGER REFERENCES secr(id),
    model_year           TEXT,
    program              TEXT,
    phase                TEXT,
    harness_family       TEXT,
    phase_implemented    TEXT,
    pull_ahead           TEXT,
    change_type          TEXT,
    subject              TEXT,
    secr_author          TEXT,
    design_release_engineer TEXT,
    change_requested_by  TEXT,
    original_issue_date  TEXT,
    reissue_date         TEXT,
    dtcr_numbers         TEXT,
    bulletin_numbers     TEXT,
    ref_secr             TEXT,
    source_def_filename  TEXT,
    enriched             INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    created_by           TEXT,
    UNIQUE (secr_number, version)
);

CREATE TABLE IF NOT EXISTS secr_affected_item (
    id        INTEGER PRIMARY KEY,
    secr_id   INTEGER NOT NULL REFERENCES secr(id) ON DELETE CASCADE,
    category  TEXT NOT NULL CHECK (category IN ('device','circuit','part_number')),
    action    TEXT NOT NULL CHECK (action IN ('ADD','CHG','DELETE')),
    item      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS secr_dtcr (
    id                    INTEGER PRIMARY KEY,
    secr_id               INTEGER NOT NULL REFERENCES secr(id) ON DELETE CASCADE,
    dtcr_number           TEXT NOT NULL,
    device_transmittal    TEXT,
    device_control_number TEXT,
    reason_for_change     TEXT,
    status                TEXT,
    match_method          TEXT,
    matched_dtx_value     TEXT,
    cnum                  TEXT,
    harness_family        TEXT
);

CREATE TABLE IF NOT EXISTS secr_dtcr_circuit (
    secr_dtcr_id INTEGER NOT NULL REFERENCES secr_dtcr(id) ON DELETE CASCADE,
    circuit      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_secr_lookup ON secr (model_year, program, phase);
CREATE INDEX IF NOT EXISTS ix_item_lookup ON secr_affected_item (item, category);
CREATE INDEX IF NOT EXISTS ix_dtcr_lookup ON secr_dtcr (dtcr_number);
CREATE INDEX IF NOT EXISTS ix_dtcr_ckt   ON secr_dtcr_circuit (circuit);
"""

# Summary-sheet cell map (see design doc §3)
_AFFECTED_CELLS = [
    ("device", "ADD", "C20"),
    ("device", "CHG", "C21"),
    ("device", "DELETE", "C22"),
    ("circuit", "ADD", "C25"),
    ("circuit", "CHG", "C26"),
    ("circuit", "DELETE", "C27"),
    ("part_number", "ADD", "C30"),
    ("part_number", "CHG", "C31"),
    ("part_number", "DELETE", "C32"),
]


# ---------------------------------------------------------------------------
# Connection / schema
# ---------------------------------------------------------------------------

def get_conn(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a connection. The caller owns it and must close it.

    Prefer :func:`connect`, which closes for you.
    """
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connect(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """A connection that commits on success, rolls back on error, and **closes**.

    ``with sqlite3.connect(...) as conn`` only manages the *transaction* — it
    leaves the connection, and therefore the file handle, open. That is
    invisible on macOS and Linux, which allow deleting an open file, but on
    Windows it locks ``secr_database.db`` and its ``-wal``/``-shm`` sidecars:
    backing up, replacing or deleting the database while the app runs fails
    with "the process cannot access the file". Closing here keeps the database
    a plain file the engineer can copy or delete between runs.
    """
    conn = get_conn(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None) -> None:
    """Create/migrate the schema. Safe to call repeatedly.

    Migrations are additive and idempotent: a v1 database keeps every row it
    has and gains the v2 change/provenance/audit tables.
    """
    with connect(db_path) as conn:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current < 1:
            conn.executescript(_SCHEMA)
        if current < 2:
            conn.executescript(_MIGRATION_V2)
            existing = {
                row["name"] for row in conn.execute("PRAGMA table_info(secr)")
            }
            for column, definition in _V2_SECR_COLUMNS.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE secr ADD COLUMN {column} {definition}")
        if current < 3:
            existing = {
                row["name"] for row in conn.execute("PRAGMA table_info(secr)")
            }
            # Columns first: the v3 indexes are defined over them.
            for column, definition in _V3_SECR_COLUMNS.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE secr ADD COLUMN {column} {definition}")
            conn.executescript(_MIGRATION_V3)
        if current < SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _split_list(text: Any) -> List[str]:
    """Split a comma/semicolon/newline-separated cell into clean items."""
    raw = _text(text)
    if not raw:
        return []
    return [p.strip() for p in re.split(r"[,;\n]+", raw) if p.strip()]


def read_secr_number(secr_bytes: bytes) -> Optional[str]:
    """Read the SECR # (Summary I2) from workbook bytes. Used to resolve
    the baseline record when running Update SECR."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(secr_bytes), data_only=True)
        value = _text(wb["Summary"]["I2"].value)
        wb.close()
        return value or None
    except Exception:
        return None


def record_from_workbook(
    secr_bytes: bytes,
    *,
    action: str,
    source_def_filename: str = "",
    filename: str = "",
    change_type: str = "",
    enriched: bool = False,
    dtcr_mapping_df=None,
    parent_secr_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a plain-dict SECR record from generated workbook bytes.

    The workbook is the source of truth (it already contains form inputs and
    any DTCR enrichment). `dtcr_mapping_df` is the DataFrame produced by
    `match_dtcr_to_harness_family()`; only rows matching the SECR's harness
    family (Summary C12) are stored, mirroring the enrichment filter.
    """
    if action not in ("create", "update"):
        raise ValueError("action must be 'create' or 'update'")

    parsed = parse_secr_bytes(secr_bytes, filename=filename)
    metadata = parsed.metadata

    record: Dict[str, Any] = {
        "secr_number": parsed.secr_number,
        "version": parsed.version,
        "filename": filename,
        "action": action,
        "parent_secr_number": parent_secr_number,
        "model_year": metadata.get("model_year", ""),
        "program": metadata.get("program", ""),
        "phase": metadata.get("phase", ""),
        "harness_family": metadata.get("harness_family", ""),
        "phase_implemented": metadata.get("phase_implemented", ""),
        "pull_ahead": metadata.get("pull_ahead", ""),
        "change_type": change_type,
        "subject": metadata.get("subject", ""),
        "secr_author": metadata.get("secr_author", ""),
        "design_release_engineer": metadata.get("design_release_engineer", ""),
        "change_requested_by": metadata.get("change_requested_by", ""),
        "original_issue_date": metadata.get("original_issue_date", ""),
        "reissue_date": metadata.get("reissue_date", ""),
        "dtcr_numbers": metadata.get("dtcr_numbers", ""),
        "bulletin_numbers": metadata.get("bulletin_numbers", ""),
        "ref_secr": metadata.get("ref_secr", ""),
        "source_def_filename": source_def_filename,
        "enriched": 1 if enriched else 0,
        "created_by": _safe_username(),
        "import_origin": "generated",
        "source_sha256": parsed.source_sha256,
        "parse_warnings": "\n".join(parsed.warnings),
        "affected_items": list(parsed.affected_items),
        "changes": [asdict(change) for change in parsed.changes],
        "dtcrs": [],
    }

    if dtcr_mapping_df is not None and len(dtcr_mapping_df) > 0:
        family = record["harness_family"]
        df = dtcr_mapping_df
        if family and "Harness Family" in df.columns:
            df = filter_dtcr_mapping_for_family(df, family)
        for _, row in df.iterrows():
            record["dtcrs"].append(
                {
                    "dtcr_number": _text(row.get("DTCR#")),
                    "device_transmittal": _text(row.get("Device Transmittal")),
                    "device_control_number": _text(
                        row.get("Extracted Device Control Number")
                    ),
                    "reason_for_change": _text(row.get("Reason for change")),
                    "status": _text(row.get("Status")),
                    "match_method": _text(row.get("Match Method")),
                    "matched_dtx_value": _text(row.get("Matched DTx Value")),
                    "cnum": _text(row.get("CNUM")),
                    "harness_family": _text(row.get("Harness Family")),
                }
            )
    return record


def _safe_username() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

#: What to do when a SECR # + version is already in the database.
CONFLICT_SKIP = "skip"        # keep what is stored, report the duplicate
CONFLICT_REPLACE = "replace"  # overwrite (used by re-generation)
CONFLICT_ERROR = "error"      # raise
CONFLICT_POLICIES = (CONFLICT_SKIP, CONFLICT_REPLACE, CONFLICT_ERROR)


class DuplicateSecrError(Exception):
    """Raised when a SECR already exists and the policy forbids replacing it."""

    def __init__(self, secr_number: str, version: str, existing_id: int) -> None:
        super().__init__(
            f"SECR {secr_number} version {version} is already in the database "
            f"(#{existing_id})."
        )
        self.secr_number = secr_number
        self.version = version
        self.existing_id = existing_id


def find_secr_id(
    secr_number: str, version: str, db_path: Optional[Path] = None
) -> Optional[int]:
    """Row id for a SECR # + version, or ``None``. This pair is the identity
    the database is keyed on."""
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM secr WHERE secr_number = ? AND version = ?",
            (str(secr_number).strip(), str(version).strip()),
        ).fetchone()
    return row["id"] if row else None


def find_secr_id_by_sha256(
    sha256: str, db_path: Optional[Path] = None
) -> Optional[int]:
    """Row id of a SECR stored from a byte-identical file, or ``None``."""
    init_db(db_path)
    if not sha256:
        return None
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT secr_id FROM secr_source_file WHERE sha256 = ? LIMIT 1",
            (sha256,),
        ).fetchone()
    return row["secr_id"] if row else None


def _log_audit(
    conn: sqlite3.Connection,
    *,
    secr_number: str,
    version: Optional[str],
    event: str,
    detail: str = "",
) -> None:
    conn.execute(
        "INSERT INTO secr_audit (secr_number, version, event, detail, by_user)"
        " VALUES (?,?,?,?,?)",
        (secr_number, version, event, detail, _safe_username()),
    )


def save_secr(
    record: Dict[str, Any],
    db_path: Optional[Path] = None,
    *,
    on_conflict: str = CONFLICT_REPLACE,
    source_bytes: Optional[bytes] = None,
) -> int:
    """Persist a SECR record with its items, changes and DTCR rows. Atomic.

    ``on_conflict`` decides what happens when the SECR # + version is already
    stored: ``replace`` (the historical behaviour, used when re-generating a
    SECR), ``skip`` (returns the existing id, used by bulk import so history is
    never silently overwritten), or ``error``. Every outcome is written to
    ``secr_audit``.

    ``source_bytes`` stores the originating workbook alongside the record for
    provenance.
    """
    if on_conflict not in CONFLICT_POLICIES:
        raise ValueError(f"on_conflict must be one of {CONFLICT_POLICIES}")
    init_db(db_path)
    with connect(db_path) as conn:
        secr_number = record["secr_number"]
        version = record["version"]
        existing = conn.execute(
            "SELECT id FROM secr WHERE secr_number = ? AND version = ?",
            (secr_number, version),
        ).fetchone()
        if existing is not None:
            if on_conflict == CONFLICT_SKIP:
                _log_audit(
                    conn,
                    secr_number=secr_number,
                    version=version,
                    event="import_skipped",
                    detail=f"already stored as #{existing['id']}",
                )
                return int(existing["id"])
            if on_conflict == CONFLICT_ERROR:
                raise DuplicateSecrError(secr_number, version, int(existing["id"]))
            _log_audit(
                conn,
                secr_number=secr_number,
                version=version,
                event="replaced",
                detail=f"previous record #{existing['id']} overwritten",
            )
            conn.execute("DELETE FROM secr WHERE id = ?", (existing["id"],))

        parent_id = None
        if record.get("parent_secr_number"):
            row = conn.execute(
                "SELECT id FROM secr WHERE secr_number = ? ORDER BY id DESC LIMIT 1",
                (record["parent_secr_number"],),
            ).fetchone()
            parent_id = row["id"] if row else None

        cur = conn.execute(
            """
            INSERT INTO secr (
                secr_number, version, filename, action, parent_secr_id,
                model_year, program, phase, harness_family, phase_implemented,
                pull_ahead, change_type, subject, secr_author,
                design_release_engineer, change_requested_by,
                original_issue_date, reissue_date, dtcr_numbers,
                bulletin_numbers, ref_secr, source_def_filename, enriched,
                created_by, import_origin, imported_at, source_sha256,
                parse_warnings, secr_sequence_number, scope_model_year,
                scope_phase, version_number, generation_date, old_def_source,
                new_def_source, metadata_provenance
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                      datetime('now','localtime'),?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record["secr_number"], record["version"], record.get("filename"),
                record["action"], parent_id,
                record.get("model_year"), record.get("program"),
                record.get("phase"), record.get("harness_family"),
                record.get("phase_implemented"), record.get("pull_ahead"),
                record.get("change_type"), record.get("subject"),
                record.get("secr_author"), record.get("design_release_engineer"),
                record.get("change_requested_by"),
                record.get("original_issue_date"), record.get("reissue_date"),
                record.get("dtcr_numbers"), record.get("bulletin_numbers"),
                record.get("ref_secr"), record.get("source_def_filename"),
                record.get("enriched", 0), record.get("created_by"),
                record.get("import_origin", ORIGIN_GENERATED),
                record.get("source_sha256"), record.get("parse_warnings"),
                record.get("secr_sequence_number"),
                record.get("scope_model_year"), record.get("scope_phase"),
                record.get("version_number"), record.get("generation_date"),
                record.get("old_def_source"), record.get("new_def_source"),
                record.get("metadata_provenance"),
            ),
        )
        secr_id = cur.lastrowid

        for it in record.get("affected_items", []):
            conn.execute(
                "INSERT INTO secr_affected_item (secr_id, category, action, item)"
                " VALUES (?,?,?,?)",
                (secr_id, it["category"], it["action"], it["item"]),
            )

        for change in record.get("changes", []):
            conn.execute(
                """
                INSERT INTO secr_change (
                    secr_id, object_type, object_id, action, field, old_value,
                    new_value, dtcr_number, harness_pn, sales_code, se_comment,
                    source_sheet, source_row
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    secr_id, change["object_type"], change["object_id"],
                    change["action"], change.get("field"),
                    change.get("old_value"), change.get("new_value"),
                    change.get("dtcr_number"), change.get("harness_pn"),
                    change.get("sales_code"), change.get("se_comment"),
                    change["source_sheet"], change["source_row"],
                ),
            )

        if source_bytes:
            conn.execute(
                """
                INSERT INTO secr_source_file
                    (secr_id, filename, sha256, size_bytes, content)
                VALUES (?,?,?,?,?)
                """,
                (
                    secr_id,
                    record.get("filename") or f"{secr_number}.xlsx",
                    record.get("source_sha256") or "",
                    len(source_bytes),
                    source_bytes,
                ),
            )

        for d in record.get("dtcrs", []):
            cur = conn.execute(
                """
                INSERT INTO secr_dtcr (
                    secr_id, dtcr_number, device_transmittal,
                    device_control_number, reason_for_change, status,
                    match_method, matched_dtx_value, cnum, harness_family
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    secr_id, d["dtcr_number"], d.get("device_transmittal"),
                    d.get("device_control_number"), d.get("reason_for_change"),
                    d.get("status"), d.get("match_method"),
                    d.get("matched_dtx_value"), d.get("cnum"),
                    d.get("harness_family"),
                ),
            )
            dtcr_id = cur.lastrowid
            for circuit in _split_list(d.get("cnum")):
                if circuit.lower() != "none":
                    conn.execute(
                        "INSERT INTO secr_dtcr_circuit (secr_dtcr_id, circuit)"
                        " VALUES (?,?)",
                        (dtcr_id, circuit),
                    )

        _log_audit(
            conn,
            secr_number=secr_number,
            version=version,
            event="saved",
            detail=(
                f"{len(record.get('changes', []))} change(s), "
                f"origin={record.get('import_origin', 'generated')}"
            ),
        )
        return secr_id


# ---------------------------------------------------------------------------
# Generated-SECR number sequences (one per model year + phase)
# ---------------------------------------------------------------------------

def peek_next_secr_number(
    model_year: str, phase: str, db_path: Optional[Path] = None
) -> int:
    """The number the next generated SECR *would* get, without reserving it.

    Used to show a preview while the engineer is still filling in the form.
    Two previews can return the same number; only
    :func:`reserve_next_secr_number` commits one.
    """
    scope_year, scope_phase = scope_key(model_year, phase)
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT next_number FROM secr_sequence WHERE model_year = ? AND phase = ?",
            (scope_year, scope_phase),
        ).fetchone()
    return int(row["next_number"]) if row else FIRST_SEQUENCE_NUMBER


def reserve_next_secr_number(
    model_year: str, phase: str, db_path: Optional[Path] = None
) -> int:
    """Atomically reserve the next SECR number for a model year + phase.

    Each ``model_year + phase`` has its own sequence starting at 1000, so
    ``MY28/X1`` and ``MY28/X2`` both issue a 1000. The sequence lives in its own
    table rather than being derived from ``MAX(secr_number) + 1``: deleting a
    SECR must not hand its number to the next one, and a number that was issued
    stays issued.

    ``BEGIN IMMEDIATE`` takes the write lock before reading, so two generation
    requests arriving together cannot both read the same value.
    """
    scope_year, scope_phase = scope_key(model_year, phase)
    if not scope_year or not scope_phase:
        raise ValueError(
            "Model Year and Phase are both required to reserve a SECR number."
        )
    init_db(db_path)
    conn = get_conn(db_path)
    try:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT next_number FROM secr_sequence WHERE model_year = ? AND phase = ?",
            (scope_year, scope_phase),
        ).fetchone()
        reserved = int(row["next_number"]) if row else FIRST_SEQUENCE_NUMBER
        conn.execute(
            """
            INSERT INTO secr_sequence (model_year, phase, next_number)
            VALUES (?,?,?)
            ON CONFLICT (model_year, phase) DO UPDATE
                SET next_number = excluded.next_number,
                    updated_at = datetime('now','localtime')
            """,
            (scope_year, scope_phase, reserved + 1),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return reserved


def list_sequences(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every numbering scope and the number it will issue next."""
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM secr_sequence ORDER BY model_year, phase"
        ).fetchall()
    return [dict(r) for r in rows]


def get_versions(
    model_year: str,
    phase: str,
    sequence_number: int,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Every stored version of one generated SECR identity, oldest first.

    Versions are separate rows: generating V2 never touches V1.
    """
    scope_year, scope_phase = scope_key(model_year, phase)
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *, (SELECT COUNT(*) FROM secr_change c WHERE c.secr_id = s.id)
                      AS change_count
            FROM secr s
            WHERE scope_model_year = ? AND scope_phase = ?
              AND secr_sequence_number = ?
            ORDER BY COALESCE(version_number, 0), id
            """,
            (scope_year, scope_phase, int(sequence_number)),
        ).fetchall()
    return [dict(r) for r in rows]


def latest_version(
    model_year: str,
    phase: str,
    sequence_number: int,
    db_path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """The newest stored version of a generated SECR identity."""
    versions = get_versions(model_year, phase, sequence_number, db_path=db_path)
    return versions[-1] if versions else None


def list_generated_secrs(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """One row per generated SECR identity, carrying its latest version.

    This is what the Update workflow offers the engineer to pick from.
    """
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT s.*, (SELECT COUNT(*) FROM secr_change c WHERE c.secr_id = s.id)
                        AS change_count
            FROM secr s
            WHERE s.secr_sequence_number IS NOT NULL
              AND s.version_number = (
                    SELECT MAX(v.version_number) FROM secr v
                    WHERE v.scope_model_year = s.scope_model_year
                      AND v.scope_phase = s.scope_phase
                      AND v.secr_sequence_number = s.secr_sequence_number
              )
            ORDER BY s.scope_model_year DESC, s.scope_phase,
                     s.secr_sequence_number DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def record_from_parsed(
    parsed: ParsedSecr,
    *,
    filename: str,
    action: str = "create",
    import_origin: str = "imported",
    change_type: str = "",
    source_def_filename: str = "",
) -> Dict[str, Any]:
    """Build a savable record from a :class:`ParsedSecr`.

    This is the import path's counterpart to :func:`record_from_workbook`;
    both produce the same record shape, so a SECR looks identical in the
    database whether it was generated here or dropped in as a file.
    """
    metadata = parsed.metadata
    return {
        "secr_number": parsed.secr_number,
        "version": parsed.version,
        "filename": filename,
        "action": action,
        "parent_secr_number": None,
        "model_year": metadata.get("model_year", ""),
        "program": metadata.get("program", ""),
        "phase": metadata.get("phase", ""),
        "harness_family": metadata.get("harness_family", ""),
        "phase_implemented": metadata.get("phase_implemented", ""),
        "pull_ahead": metadata.get("pull_ahead", ""),
        "change_type": change_type,
        "subject": metadata.get("subject", ""),
        "secr_author": metadata.get("secr_author", ""),
        "design_release_engineer": metadata.get("design_release_engineer", ""),
        "change_requested_by": metadata.get("change_requested_by", ""),
        "original_issue_date": metadata.get("original_issue_date", ""),
        "reissue_date": metadata.get("reissue_date", ""),
        "dtcr_numbers": metadata.get("dtcr_numbers", ""),
        "bulletin_numbers": metadata.get("bulletin_numbers", ""),
        "ref_secr": metadata.get("ref_secr", ""),
        "source_def_filename": source_def_filename,
        "enriched": 0,
        "created_by": _safe_username(),
        "import_origin": import_origin,
        "source_sha256": parsed.source_sha256,
        "parse_warnings": "\n".join(parsed.warnings),
        "affected_items": list(parsed.affected_items),
        "changes": [asdict(change) for change in parsed.changes],
        "dtcrs": [],
    }


def delete_secr(secr_id: int, db_path: Optional[Path] = None) -> bool:
    """Delete a SECR and every record hanging off it, in one transaction.

    Returns ``False`` if the id does not exist. The deletion is recorded in
    ``secr_audit`` with the change count, so removing a record still leaves a
    trace that it was there.
    """
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT secr_number, version FROM secr WHERE id = ?", (secr_id,)
        ).fetchone()
        if row is None:
            return False
        change_count = conn.execute(
            "SELECT COUNT(*) FROM secr_change WHERE secr_id = ?", (secr_id,)
        ).fetchone()[0]
        conn.execute("DELETE FROM secr WHERE id = ?", (secr_id,))
        _log_audit(
            conn,
            secr_number=row["secr_number"],
            version=row["version"],
            event="deleted",
            detail=f"{change_count} change record(s) removed with it",
        )
        return True


def get_source_file(
    secr_id: int, db_path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """The stored original workbook for a SECR, or ``None`` if not kept."""
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT filename, sha256, size_bytes, content, stored_at"
            " FROM secr_source_file WHERE secr_id = ?",
            (secr_id,),
        ).fetchone()
    return dict(row) if row else None


def get_audit_log(
    secr_number: str = "", limit: int = 200, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Audit entries, newest first, optionally for one SECR number."""
    init_db(db_path)
    clause = "WHERE secr_number = ?" if secr_number else ""
    params: List[Any] = [secr_number] if secr_number else []
    params.append(limit)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM secr_audit {clause} ORDER BY id DESC LIMIT ?", params
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def list_secrs(
    model_year: str = "",
    program: str = "",
    phase: str = "",
    harness_family: str = "",
    author: str = "",
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """List SECR records, newest first, with optional exact-match filters."""
    init_db(db_path)
    clauses, params = [], []
    for col, val in (
        ("model_year", model_year), ("program", program), ("phase", phase),
        ("harness_family", harness_family), ("secr_author", author),
    ):
        if val:
            clauses.append(f"{col} = ?")
            params.append(val)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM secr {where} ORDER BY id DESC", params
        ).fetchall()
    return [dict(r) for r in rows]


#: Columns a browser row needs, plus the change count, in one query.
_BROWSER_SELECT = """
SELECT s.*,
       (SELECT COUNT(*) FROM secr_change c WHERE c.secr_id = s.id) AS change_count
FROM secr s
"""


def search_secrs(
    query: str = "",
    *,
    program: str = "",
    model_year: str = "",
    bulletin: str = "",
    harness_family: str = "",
    phase: str = "",
    dtcr: str = "",
    change_type: str = "",
    object_type: str = "",
    limit: int = 500,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """The database browser's one query: free-text search plus combinable filters.

    ``query`` matches a SECR number, subject, DTCR, bulletin, or any change's
    object id (a CNUM like ``D2784J``, a circuit like ``A937F``, a connector
    part number) — matching either exactly or as a prefix, so searching
    ``A937`` also finds ``A937F``. Every returned row carries ``match_reason``
    explaining why it matched.
    """
    init_db(db_path)
    clauses: List[str] = []
    params: List[Any] = []

    for column, value in (
        ("s.program", program),
        ("s.model_year", model_year),
        ("s.harness_family", harness_family),
        ("s.phase", phase),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)

    if bulletin:
        clauses.append("s.bulletin_numbers LIKE ?")
        params.append(f"%{bulletin}%")

    if dtcr:
        clauses.append(
            "(s.dtcr_numbers LIKE ?"
            " OR EXISTS (SELECT 1 FROM secr_change c WHERE c.secr_id = s.id"
            "            AND c.dtcr_number = ?)"
            " OR EXISTS (SELECT 1 FROM secr_dtcr d WHERE d.secr_id = s.id"
            "            AND d.dtcr_number = ?))"
        )
        params.extend([f"%{dtcr}%", dtcr.strip(), dtcr.strip()])

    if change_type:
        clauses.append(
            "EXISTS (SELECT 1 FROM secr_change c WHERE c.secr_id = s.id"
            "        AND c.action = ?)"
        )
        params.append(change_type)

    if object_type:
        clauses.append(
            "EXISTS (SELECT 1 FROM secr_change c WHERE c.secr_id = s.id"
            "        AND c.object_type = ?)"
        )
        params.append(object_type)

    term = query.strip()
    if term:
        like = f"{term}%"
        clauses.append(
            "(s.secr_number LIKE ? OR s.subject LIKE ? OR s.dtcr_numbers LIKE ?"
            " OR s.bulletin_numbers LIKE ? OR s.harness_family LIKE ?"
            " OR EXISTS (SELECT 1 FROM secr_change c WHERE c.secr_id = s.id"
            "            AND (c.object_id LIKE ? OR c.new_value LIKE ?"
            "                 OR c.old_value LIKE ? OR c.dtcr_number LIKE ?))"
            " OR EXISTS (SELECT 1 FROM secr_affected_item a WHERE a.secr_id = s.id"
            "            AND a.item LIKE ?))"
        )
        params.extend(
            [f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%"]
            + [like, like, like, like, like]
        )

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"{_BROWSER_SELECT} {where} ORDER BY s.id DESC LIMIT ?", params
        ).fetchall()
        results = [dict(r) for r in rows]
        for result in results:
            result["match_reason"] = (
                _match_reason(conn, result, term) if term else ""
            )
    return results


def _match_reason(
    conn: sqlite3.Connection, record: Dict[str, Any], term: str
) -> str:
    """Explain why a search hit matched, so results are auditable."""
    reasons: List[str] = []
    lowered = term.lower()
    for label, value in (
        ("SECR #", record.get("secr_number")),
        ("subject", record.get("subject")),
        ("DTCR #", record.get("dtcr_numbers")),
        ("bulletin", record.get("bulletin_numbers")),
        ("harness family", record.get("harness_family")),
    ):
        if value and lowered in str(value).lower():
            reasons.append(label)

    hits = conn.execute(
        """
        SELECT object_type, object_id, COUNT(*) AS n FROM secr_change
        WHERE secr_id = ?
          AND (object_id LIKE ? OR new_value LIKE ? OR old_value LIKE ?
               OR dtcr_number LIKE ?)
        GROUP BY object_type, object_id ORDER BY n DESC LIMIT 3
        """,
        (record["id"], f"{term}%", f"{term}%", f"{term}%", f"{term}%"),
    ).fetchall()
    for hit in hits:
        reasons.append(f"{hit['object_type']} {hit['object_id']} ({hit['n']})")
    return ", ".join(reasons)


def get_changes(
    secr_id: int,
    *,
    object_type: str = "",
    action: str = "",
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Change records for one SECR, optionally narrowed by type or action."""
    init_db(db_path)
    clauses = ["secr_id = ?"]
    params: List[Any] = [secr_id]
    if object_type:
        clauses.append("object_type = ?")
        params.append(object_type)
    if action:
        clauses.append("action = ?")
        params.append(action)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM secr_change WHERE {' AND '.join(clauses)}"
            " ORDER BY object_type, object_id, id",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def _change_filter_sql(
    *,
    query: str = "",
    object_type: str = "",
    object_id: str = "",
    cnum: str = "",
    circuit: str = "",
    dtcr_number: str = "",
    harness_family: str = "",
    program: str = "",
    model_year: str = "",
    phase: str = "",
    bulletin: str = "",
    action: str = "",
) -> tuple:
    """Build the WHERE clause shared by the change table and its facet counts.

    One clause builder means the charts, the counters and the rows can never
    disagree about what is being shown.
    """
    clauses: List[str] = []
    params: List[Any] = []
    for column, value in (
        ("c.object_type", object_type),
        ("c.action", action),
        ("c.dtcr_number", dtcr_number),
        ("s.harness_family", harness_family),
        ("s.program", program),
        ("s.model_year", model_year),
        ("s.phase", phase),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if object_id:
        clauses.append("c.object_id LIKE ?")
        params.append(f"{object_id.strip()}%")
    # A CNUM and a circuit are different questions even though both live in
    # `object_id`; keeping them as separate filter keys lets the connector
    # chart and the circuit chart each ignore only its own selection.
    for kind, value in (("connector", cnum), ("circuit", circuit)):
        if value:
            clauses.append("(c.object_type = ? AND c.object_id LIKE ?)")
            params.extend([kind, f"{value.strip()}%"])
    if bulletin:
        clauses.append("s.bulletin_numbers LIKE ?")
        params.append(f"%{bulletin.strip()}%")

    term = query.strip()
    if term:
        clauses.append(
            "(c.object_id LIKE ? OR c.old_value LIKE ? OR c.new_value LIKE ?"
            " OR c.dtcr_number LIKE ? OR c.se_comment LIKE ?"
            " OR s.secr_number LIKE ? OR s.harness_family LIKE ?"
            " OR s.bulletin_numbers LIKE ?)"
        )
        params.extend([f"{term}%"] * 4 + [f"%{term}%"] * 4)
    return clauses, params


def find_changes(
    *,
    limit: int = 1000,
    db_path: Optional[Path] = None,
    **filters: Any,
) -> List[Dict[str, Any]]:
    """Changes across every SECR, joined to their SECR's identifying columns.

    This is the workhorse behind the engineering query views ("every change
    that touched CNUM D2784J", "every change under DTCR 50319").
    """
    init_db(db_path)
    clauses, params = _change_filter_sql(**filters)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params = list(params) + [limit]
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT c.*, s.secr_number, s.version, s.program, s.model_year,
                   s.harness_family, s.phase, s.bulletin_numbers
            FROM secr_change c JOIN secr s ON s.id = c.secr_id
            {where}
            ORDER BY s.id DESC, c.object_type, c.object_id LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


#: Facet name -> (SQL expression it groups by, the filter key it drives).
#: Each facet becomes one chart, and a chart never filters itself — otherwise
#: selecting a value collapses its own chart to a single bar and there is no
#: way to see or switch to a sibling.
_CHANGE_FACETS = {
    "action": ("c.action", "action"),
    "object_type": ("c.object_type", "object_type"),
    "harness_family": ("s.harness_family", "harness_family"),
    "dtcr_number": ("c.dtcr_number", "dtcr_number"),
    "program": ("s.program", "program"),
    "model_year": ("s.model_year", "model_year"),
}


def change_facets(
    *,
    top_n: int = 12,
    db_path: Optional[Path] = None,
    **filters: Any,
) -> Dict[str, Any]:
    """Counts for every chart on the explorer, under one set of filters.

    Returns the headline totals plus, per facet, ``[{"name", "n"}]`` ordered by
    count. ``connectors`` and ``circuits`` are the most-changed objects of each
    kind — the "which CNUM moves most" question — and are faceted separately
    from ``object_type`` because they are different questions.
    """
    init_db(db_path)
    join = "FROM secr_change c JOIN secr s ON s.id = c.secr_id"

    def _where(*, without: str = "") -> tuple:
        """The filter clause, optionally with one filter key left out."""
        applied = {k: v for k, v in filters.items() if k != without or not without}
        clauses, params = _change_filter_sql(**applied)
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", list(params)

    result: Dict[str, Any] = {}
    with connect(db_path) as conn:
        where, params = _where()
        totals = conn.execute(
            f"""
            SELECT COUNT(*) AS changes,
                   COUNT(DISTINCT c.secr_id) AS secrs,
                   COUNT(DISTINCT CASE WHEN c.object_type = 'connector'
                                       THEN c.object_id END) AS connectors,
                   COUNT(DISTINCT CASE WHEN c.object_type = 'circuit'
                                       THEN c.object_id END) AS circuits,
                   COUNT(DISTINCT CASE WHEN c.dtcr_number != ''
                                       THEN c.dtcr_number END) AS dtcrs
            {join} {where}
            """,
            params,
        ).fetchone()
        result["totals"] = dict(totals)

        for name, (expression, filter_key) in _CHANGE_FACETS.items():
            facet_where, facet_params = _where(without=filter_key)
            rows = conn.execute(
                f"""
                SELECT {expression} AS name, COUNT(*) AS n
                {join} {facet_where}
                {'AND' if facet_where else 'WHERE'} {expression} IS NOT NULL
                    AND {expression} != ''
                GROUP BY name ORDER BY n DESC, name LIMIT ?
                """,
                facet_params + [top_n],
            ).fetchall()
            result[name] = [dict(r) for r in rows]

        for name, kind, own_filter in (
            ("connectors", "connector", "cnum"),
            ("circuits", "circuit", "circuit"),
        ):
            facet_where, facet_params = _where(without=own_filter)
            rows = conn.execute(
                f"""
                SELECT c.object_id AS name, COUNT(*) AS n
                {join} {facet_where}
                {'AND' if facet_where else 'WHERE'} c.object_type = ?
                GROUP BY name ORDER BY n DESC, name LIMIT ?
                """,
                facet_params + [kind, top_n],
            ).fetchall()
            result[name] = [dict(r) for r in rows]
    return result


def distinct_values(column: str, db_path: Optional[Path] = None) -> List[str]:
    """Distinct non-empty values of a ``secr`` column, for filter dropdowns."""
    allowed = {
        "program", "model_year", "phase", "harness_family", "secr_author",
        "change_type", "import_origin",
    }
    if column not in allowed:
        raise ValueError(f"{column!r} is not a filterable column")
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT DISTINCT {column} AS value FROM secr"
            f" WHERE {column} IS NOT NULL AND {column} != '' ORDER BY value"
        ).fetchall()
    return [str(r["value"]) for r in rows]


def distinct_change_actions(db_path: Optional[Path] = None) -> List[str]:
    """Distinct change actions present in the database, for the type filter."""
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT action FROM secr_change ORDER BY action"
        ).fetchall()
    return [str(r["action"]) for r in rows]


def database_summary(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Counts for the dashboard: totals plus breakdowns by the usual axes."""
    init_db(db_path)

    def _grouped(conn: sqlite3.Connection, sql: str) -> List[Dict[str, Any]]:
        return [dict(r) for r in conn.execute(sql).fetchall()]

    with connect(db_path) as conn:
        totals = {
            "secrs": conn.execute("SELECT COUNT(*) FROM secr").fetchone()[0],
            "changes": conn.execute("SELECT COUNT(*) FROM secr_change").fetchone()[0],
            "programs": conn.execute(
                "SELECT COUNT(DISTINCT program) FROM secr WHERE program != ''"
            ).fetchone()[0],
        }
        return {
            "totals": totals,
            "by_program": _grouped(
                conn,
                "SELECT program AS name, COUNT(*) AS n FROM secr"
                " WHERE program != '' GROUP BY program ORDER BY n DESC",
            ),
            "by_model_year": _grouped(
                conn,
                "SELECT model_year AS name, COUNT(*) AS n FROM secr"
                " WHERE model_year != '' GROUP BY model_year ORDER BY name",
            ),
            "by_harness_family": _grouped(
                conn,
                "SELECT harness_family AS name, COUNT(*) AS n FROM secr"
                " WHERE harness_family != '' GROUP BY harness_family ORDER BY n DESC",
            ),
            "changes_by_action": _grouped(
                conn,
                "SELECT action AS name, COUNT(*) AS n FROM secr_change"
                " GROUP BY action ORDER BY n DESC",
            ),
            "changes_by_object_type": _grouped(
                conn,
                "SELECT object_type AS name, COUNT(*) AS n FROM secr_change"
                " GROUP BY object_type ORDER BY n DESC",
            ),
            "top_dtcrs": _grouped(
                conn,
                "SELECT dtcr_number AS name, COUNT(*) AS n FROM secr_change"
                " WHERE dtcr_number IS NOT NULL AND dtcr_number != ''"
                " GROUP BY dtcr_number ORDER BY n DESC LIMIT 10",
            ),
        }


def get_secr(secr_id: int, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Full record: secr row + affected items + change records + DTCR rows."""
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM secr WHERE id = ?", (secr_id,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["affected_items"] = [
            dict(r)
            for r in conn.execute(
                "SELECT category, action, item FROM secr_affected_item"
                " WHERE secr_id = ? ORDER BY category, action, item",
                (secr_id,),
            )
        ]
        record["dtcrs"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM secr_dtcr WHERE secr_id = ? ORDER BY dtcr_number",
                (secr_id,),
            )
        ]
        record["changes"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM secr_change WHERE secr_id = ?"
                " ORDER BY object_type, object_id, id",
                (secr_id,),
            )
        ]
        source = conn.execute(
            "SELECT filename, sha256, size_bytes, stored_at FROM secr_source_file"
            " WHERE secr_id = ?",
            (secr_id,),
        ).fetchone()
        record["source_file"] = dict(source) if source else None
        record["warnings"] = [
            line for line in (record.get("parse_warnings") or "").split("\n") if line
        ]
        return record


def find_by_dtcr(dtcr_number: str, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """All SECRs that include a given DTCR # (via enrichment rows or the raw
    C14 text)."""
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT s.* FROM secr s
            LEFT JOIN secr_dtcr d ON d.secr_id = s.id
            WHERE d.dtcr_number = ? OR s.dtcr_numbers LIKE ?
            ORDER BY s.id DESC
            """,
            (str(dtcr_number).strip(), f"%{str(dtcr_number).strip()}%"),
        ).fetchall()
    return [dict(r) for r in rows]


def find_by_item(item: str, category: str = "", db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """All SECRs whose affected items (device / circuit / part_number) or
    per-DTCR circuits include `item`."""
    init_db(db_path)
    params: List[Any] = [item.strip()]
    cat_clause = ""
    if category:
        cat_clause = "AND a.category = ?"
        params.append(category)
    params.append(item.strip())
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT s.* FROM secr s
            LEFT JOIN secr_affected_item a ON a.secr_id = s.id
            LEFT JOIN secr_dtcr d ON d.secr_id = s.id
            LEFT JOIN secr_dtcr_circuit c ON c.secr_dtcr_id = d.id
            WHERE (a.item = ? {cat_clause}) OR c.circuit = ?
            ORDER BY s.id DESC
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_revision_chain(secr_id: int, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Walk parent links from a record back to its original SECR."""
    init_db(db_path)
    chain: List[Dict[str, Any]] = []
    with connect(db_path) as conn:
        current: Optional[int] = secr_id
        seen = set()
        while current is not None and current not in seen:
            seen.add(current)
            row = conn.execute("SELECT * FROM secr WHERE id = ?", (current,)).fetchone()
            if row is None:
                break
            chain.append(dict(row))
            current = row["parent_secr_id"]
    return chain


def next_sequence(
    model_year: str,
    program: str,
    phase: str,
    change_type: str,
    default: int = 1000,
    db_path: Optional[Path] = None,
) -> int:
    """Next free sequence for SECR numbers shaped {M|D}{MY2}{PROGRAM}{PHASE}_{seq}."""
    my_two = str(model_year).strip()[-2:]
    prefix = (
        ("D" if str(change_type).strip().lower().startswith("design") else "M")
        + my_two
        + str(program).replace(" ", "").upper()
        + str(phase).replace("_", "").replace(" ", "").upper()
        + "_"
    )
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT secr_number FROM secr WHERE secr_number LIKE ?", (prefix + "%",)
        ).fetchall()
    best = default - 1
    for r in rows:
        m = re.search(r"_(\d+)$", r["secr_number"])
        if m:
            best = max(best, int(m.group(1)))
    return best + 1
