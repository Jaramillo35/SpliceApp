"""Bulk SECR import — many workbooks in, one auditable report out.

The import service sits between the UI and the database:

    files -> parse_secr_bytes() -> record_from_parsed() -> save_secr()

Every file produces exactly one :class:`ImportResult`, whatever happens to it.
A file is never dropped silently: it is imported, reported as an existing
duplicate, or reported as failed with the reason. Duplicates default to
``skip`` so an import can never overwrite engineering history that is already
stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from secrdb.core.common.errors import SpliceError
from secrdb.core.common.logging import get_logger
from secrdb.core.secr import db as secr_db
from secrdb.core.secr.parse import parse_secr_bytes

logger = get_logger(__name__)

#: Outcomes, in the order the summary reports them.
STATUS_IMPORTED = "imported"
STATUS_DUPLICATE = "duplicate"
STATUS_REPLACED = "replaced"
STATUS_FAILED = "failed"


@dataclass
class ImportResult:
    """What happened to one file."""

    filename: str
    status: str
    secr_number: str = ""
    version: str = ""
    change_count: int = 0
    secr_id: Optional[int] = None
    message: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in (STATUS_IMPORTED, STATUS_REPLACED)


@dataclass
class ImportSummary:
    """The whole run, as the UI reports it back to the engineer."""

    results: List[ImportResult] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return len(self.results)

    @property
    def imported(self) -> List[ImportResult]:
        return [r for r in self.results if r.status == STATUS_IMPORTED]

    @property
    def replaced(self) -> List[ImportResult]:
        return [r for r in self.results if r.status == STATUS_REPLACED]

    @property
    def duplicates(self) -> List[ImportResult]:
        return [r for r in self.results if r.status == STATUS_DUPLICATE]

    @property
    def failed(self) -> List[ImportResult]:
        return [r for r in self.results if r.status == STATUS_FAILED]

    @property
    def total_changes(self) -> int:
        return sum(r.change_count for r in self.results if r.ok)

    @property
    def with_warnings(self) -> List[ImportResult]:
        return [r for r in self.results if r.warnings]

    def headline(self) -> str:
        """One-line summary, e.g. '24 SECR files processed'."""
        noun = "file" if self.processed == 1 else "files"
        return f"{self.processed} SECR {noun} processed"

    def counts(self) -> Dict[str, int]:
        return {
            STATUS_IMPORTED: len(self.imported),
            STATUS_REPLACED: len(self.replaced),
            STATUS_DUPLICATE: len(self.duplicates),
            STATUS_FAILED: len(self.failed),
        }


def import_secr_bytes(
    secr_bytes: bytes,
    filename: str,
    *,
    on_conflict: str = secr_db.CONFLICT_SKIP,
    store_source: bool = True,
    db_path: Optional[Path] = None,
) -> ImportResult:
    """Import one SECR workbook. Never raises for a bad file — it reports it."""
    try:
        parsed = parse_secr_bytes(secr_bytes, filename=filename)
    except SpliceError as exc:
        logger.warning("SECR import rejected %s: %s", filename, exc)
        return ImportResult(filename=filename, status=STATUS_FAILED, message=str(exc))
    except Exception as exc:  # noqa: BLE001 - a corrupt file must not stop the run
        logger.exception("Unexpected failure parsing %s", filename)
        return ImportResult(
            filename=filename,
            status=STATUS_FAILED,
            message=f"Unexpected error while reading the file: {exc}",
        )

    existing_id = secr_db.find_secr_id(
        parsed.secr_number, parsed.version, db_path=db_path
    )
    record = secr_db.record_from_parsed(parsed, filename=filename)

    try:
        secr_id = secr_db.save_secr(
            record,
            db_path,
            on_conflict=on_conflict,
            source_bytes=secr_bytes if store_source else None,
        )
    except secr_db.DuplicateSecrError as exc:
        return ImportResult(
            filename=filename,
            status=STATUS_DUPLICATE,
            secr_number=parsed.secr_number,
            version=parsed.version,
            secr_id=exc.existing_id,
            message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to save %s", filename)
        return ImportResult(
            filename=filename,
            status=STATUS_FAILED,
            secr_number=parsed.secr_number,
            version=parsed.version,
            message=f"Could not save to the database: {exc}",
        )

    if existing_id is not None and on_conflict == secr_db.CONFLICT_SKIP:
        return ImportResult(
            filename=filename,
            status=STATUS_DUPLICATE,
            secr_number=parsed.secr_number,
            version=parsed.version,
            secr_id=secr_id,
            message=f"Already in the database as record #{secr_id}; kept the stored one.",
            warnings=list(parsed.warnings),
        )

    return ImportResult(
        filename=filename,
        status=STATUS_REPLACED if existing_id is not None else STATUS_IMPORTED,
        secr_number=parsed.secr_number,
        version=parsed.version,
        change_count=parsed.change_count,
        secr_id=secr_id,
        message=(
            f"Replaced record #{existing_id}."
            if existing_id is not None
            else f"Imported {parsed.change_count} change record(s)."
        ),
        warnings=list(parsed.warnings),
    )


def import_secr_files(
    files: Sequence[Tuple[str, bytes]],
    *,
    on_conflict: str = secr_db.CONFLICT_SKIP,
    store_source: bool = True,
    progress: Optional[Callable[[int, int, str], None]] = None,
    db_path: Optional[Path] = None,
) -> ImportSummary:
    """Import many ``(filename, bytes)`` pairs and report on every one.

    ``progress`` is called as ``(done, total, filename)`` after each file so
    the UI can drive a progress bar without knowing anything about parsing.
    """
    summary = ImportSummary()
    total = len(files)
    for index, (filename, payload) in enumerate(files, start=1):
        summary.results.append(
            import_secr_bytes(
                payload,
                filename,
                on_conflict=on_conflict,
                store_source=store_source,
                db_path=db_path,
            )
        )
        if progress:
            progress(index, total, filename)
    logger.info(
        "SECR import finished: %s (%s)", summary.headline(), summary.counts()
    )
    return summary


def import_folder(
    folder: Path,
    *,
    pattern: str = "*.xlsx",
    on_conflict: str = secr_db.CONFLICT_SKIP,
    store_source: bool = True,
    db_path: Optional[Path] = None,
) -> ImportSummary:
    """Import every SECR workbook in a folder. Used for backfills and tests."""
    folder = Path(folder)
    if not folder.is_dir():
        raise SpliceError(f"{folder} is not a folder.")
    files: List[Tuple[str, bytes]] = []
    for path in sorted(folder.glob(pattern)):
        if path.name.startswith("~$"):  # Excel lock files
            continue
        files.append((path.name, path.read_bytes()))
    return import_secr_files(
        files,
        on_conflict=on_conflict,
        store_source=store_source,
        db_path=db_path,
    )
