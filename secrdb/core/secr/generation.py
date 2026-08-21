"""Generated-SECR workflows: create a new SECR, or update an existing one.

Two workflows, deliberately separate:

``Create New SECR``      OLD/NEW DEF compare → metadata → validate → reserve a
                         number in the ``MY + Phase`` scope → V1 → generate → store
``Update Existing SECR`` existing SECR + new DEF compare → compare metadata →
                         same scope? next version : **stop and recommend a new SECR**

Both run the same deterministic comparison engine
(:mod:`secrdb.core.secr.generate`); this module only decides identity, numbering,
naming and versioning around it, and is UI-independent so the Streamlit page,
a script, or a future API can drive the identical flow.

A number is reserved only at the moment of confirmed generation — previewing a
form never consumes one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from secrdb.core.common.errors import SpliceInputError
from secrdb.core.common.logging import get_logger
from secrdb.core.secr import db as secr_db
from secrdb.core.secr.enrich import filter_dtcr_mapping_for_family
from secrdb.core.secr.generate import create_secr_bytes, update_secr_bytes
from secrdb.core.secr.numbering import auto_enrich_secr
from secrdb.core.secr.identity import (
    CHANGE_TYPE_DESIGN,
    MetadataDifference,
    SecrIdentity,
    SecrMetadata,
    build_filename,
    build_secr_number,
    changed_fields,
    compare_metadata,
    extract_metadata_from_def,
    format_generation_date,
    identity_from_metadata,
    scope_key,
    validate_metadata,
)

logger = get_logger(__name__)


class SecrScopeChanged(SpliceInputError):
    """The new DEF describes a different SECR than the one being updated.

    Carries the field-by-field comparison so the UI can show exactly what moved.
    """

    def __init__(
        self, identity: SecrIdentity, differences: List[MetadataDifference]
    ) -> None:
        changed = changed_fields(differences)
        names = ", ".join(f"{d.label} {d.existing} → {d.new}" for d in changed)
        super().__init__(
            f"The new DEF changes the scope of SECR {identity}: {names}. "
            "A change of Harness Family, Model Year, Phase or Program normally "
            "requires a new SECR."
        )
        self.identity = identity
        self.differences = differences
        self.changed = changed


@dataclass
class NewSecrPlan:
    """What a new SECR *would* be, shown for confirmation before generating."""

    metadata: SecrMetadata
    change_type: str
    sequence_number: int
    version_number: int = 1
    generation_date: date = field(default_factory=date.today)
    secr_number: str = ""
    filename: str = ""
    sources: Dict[str, str] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    old_def_source: str = ""
    new_def_source: str = ""
    scope_is_new: bool = False

    @property
    def can_generate(self) -> bool:
        """Generation is blocked only while a required value is *missing*.

        A disagreement between the two DEFs is a ``warning``, not a problem:
        the engineer sees it and decides. Only metadata that cannot produce a
        SECR number at all stops the generation.
        """
        return not self.problems

    @property
    def identity(self) -> SecrIdentity:
        return identity_from_metadata(self.metadata, self.sequence_number)


@dataclass
class UpdateSecrPlan:
    """What the next version of an existing SECR would be."""

    identity: SecrIdentity
    existing: Dict[str, Any]
    existing_metadata: SecrMetadata
    new_metadata: SecrMetadata
    differences: List[MetadataDifference]
    change_type: str
    current_version: int
    next_version: int
    generation_date: date = field(default_factory=date.today)
    secr_number: str = ""
    filename: str = ""
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    old_def_source: str = ""
    new_def_source: str = ""

    @property
    def changed(self) -> List[MetadataDifference]:
        return changed_fields(self.differences)

    @property
    def scope_changed(self) -> bool:
        return bool(self.changed)

    @property
    def can_generate(self) -> bool:
        """Blocked by a scope change as well as by invalid metadata.

        There is no override: for the MVP a scope change means the engineer
        creates a new SECR, which is the safe outcome.
        """
        return not self.problems and not self.scope_changed


@dataclass
class DtcrAssignment:
    """One DTCR attached to one CNUM's change records."""

    cnum: str
    dtcr_number: str
    harness_family: str
    change_count: int
    source: str


@dataclass
class GeneratedSecr:
    """A generated SECR: the workbook, its identity, and its database record."""

    secr_bytes: bytes
    filename: str
    secr_number: str
    identity: SecrIdentity
    version_number: int
    secr_id: int
    change_count: int
    metadata: SecrMetadata
    warnings: List[str] = field(default_factory=list)
    enriched: bool = False
    enrichment_summary: Any = None
    dtcr_assignments: List[DtcrAssignment] = field(default_factory=list)

    @property
    def assigned_change_count(self) -> int:
        return sum(a.change_count for a in self.dtcr_assignments)


# ---------------------------------------------------------------------------
# DTCR → CNUM assignment
# ---------------------------------------------------------------------------

def _normalize_cnum(value: Any) -> str:
    text = str(value or "").strip().upper()
    return "" if text in ("", "NONE", "NAN") else text


def build_cnum_dtcr_map(dtcr_mapping_df) -> Dict[str, List[Dict[str, str]]]:
    """``{CNUM: [{dtcr_number, harness_family}, ...]}`` from a matching report.

    The DTCR Matching Report's ``CNUM`` column may list several connectors for
    one DTCR, so each is split out. Rows without a CNUM are skipped — a DTCR
    that was never matched to a connector is not assigned to one here.
    """
    mapping: Dict[str, List[Dict[str, str]]] = {}
    if dtcr_mapping_df is None or len(dtcr_mapping_df) == 0:
        return mapping
    if "CNUM" not in dtcr_mapping_df.columns:
        return mapping

    for _, row in dtcr_mapping_df.iterrows():
        dtcr_number = str(row.get("DTCR#") or "").strip()
        if not dtcr_number:
            continue
        family = str(row.get("Harness Family") or "").strip()
        for part in re.split(r"[,;/\n]+", str(row.get("CNUM") or "")):
            cnum = _normalize_cnum(part)
            if not cnum:
                continue
            entries = mapping.setdefault(cnum, [])
            if not any(e["dtcr_number"] == dtcr_number for e in entries):
                entries.append(
                    {"dtcr_number": dtcr_number, "harness_family": family}
                )
    return mapping


def assign_dtcrs_to_cnums(
    changes: List[Dict[str, Any]], dtcr_mapping_df
) -> List[DtcrAssignment]:
    """Attach DTCR numbers to connector changes, in place.

    A change row already carrying a DTCR parsed from its SE comment keeps it —
    what the engineer wrote on the row is the stronger statement. Rows without
    one are assigned the DTCR the matching report ties to that CNUM. When the
    report maps several DTCRs to one CNUM, they are recorded together
    (``"49754, 50319"``) rather than one being picked arbitrarily.

    Returns what was assigned, so the UI can show it and nothing happens
    invisibly.
    """
    mapping = build_cnum_dtcr_map(dtcr_mapping_df)
    if not mapping:
        return []

    assignments: Dict[tuple, DtcrAssignment] = {}
    for change in changes:
        if change.get("object_type") != "connector":
            continue
        cnum = _normalize_cnum(change.get("object_id"))
        entries = mapping.get(cnum)
        if not entries:
            continue

        numbers = ", ".join(entry["dtcr_number"] for entry in entries)
        family = entries[0]["harness_family"]
        if change.get("dtcr_number"):
            source = "SE comment"          # already stated on the row; left alone
            recorded = str(change["dtcr_number"])
        else:
            source = "DTCR Matching Report"
            change["dtcr_number"] = numbers
            recorded = numbers

        key = (cnum, recorded, source)
        existing = assignments.get(key)
        if existing is None:
            assignments[key] = DtcrAssignment(
                cnum=cnum,
                dtcr_number=recorded,
                harness_family=family,
                change_count=1,
                source=source,
            )
        else:
            existing.change_count += 1
    return sorted(assignments.values(), key=lambda a: (a.cnum, a.dtcr_number))


# ---------------------------------------------------------------------------
# Create New SECR
# ---------------------------------------------------------------------------

def plan_new_secr(
    def_bytes: bytes,
    def_filename: str,
    change_type: str = CHANGE_TYPE_DESIGN,
    *,
    when: Optional[date] = None,
    db_path: Optional[Path] = None,
) -> NewSecrPlan:
    """Work out what a new SECR would be, without reserving its number.

    Extracts the scope from the DEF compare, validates it, and previews the
    number, version and filename.

    A value that is **missing** lands in ``problems`` and blocks generation —
    nothing is guessed, because there is no SECR number to build without it. A
    value the two DEFs **disagree** about lands in ``warnings`` and does not
    block: the scope comes from the NEW DEF, and whether an unusual pairing is
    a mistake is the engineer's call, not the tool's.
    """
    extracted = extract_metadata_from_def(def_bytes, def_filename)
    metadata = extracted.metadata
    problems = validate_metadata(metadata, change_type)
    if extracted.read_error:
        problems.insert(0, extracted.read_error)

    sequence_number = 0
    scope_is_new = False
    secr_number = ""
    filename = ""
    when = when or date.today()

    if not problems:
        sequence_number = secr_db.peek_next_secr_number(
            metadata.model_year, metadata.phase, db_path=db_path
        )
        scope_is_new = not any(
            (row["model_year"], row["phase"])
            == scope_key(metadata.model_year, metadata.phase)
            for row in secr_db.list_sequences(db_path=db_path)
        )
        secr_number = build_secr_number(metadata, change_type, sequence_number)
        filename = build_filename(metadata, change_type, sequence_number, 1, when)

    return NewSecrPlan(
        metadata=metadata,
        change_type=change_type,
        sequence_number=sequence_number,
        generation_date=when,
        secr_number=secr_number,
        filename=filename,
        sources=extracted.sources,
        notes=list(extracted.notes),
        warnings=list(extracted.warnings),
        problems=problems,
        old_def_source=extracted.old_def_source,
        new_def_source=extracted.new_def_source,
        scope_is_new=scope_is_new,
    )


def generate_new_secr(
    def_bytes: bytes,
    def_filename: str,
    plan: NewSecrPlan,
    *,
    reason_for_change: str = "",
    secr_author: str = "",
    design_release_engineer: str = "",
    change_requested_by: str = "",
    original_issue_date: str = "",
    phase_implemented: str = "",
    pull_ahead: str = "",
    dtcr_matching_bytes: Optional[bytes] = None,
    db_path: Optional[Path] = None,
) -> GeneratedSecr:
    """Reserve a number, build the SECR workbook, and store it. V1.

    The number is reserved here — after the engineer confirms — so previewing a
    form never burns one. Reservation is transactional and is never rolled back
    if a later step fails: a number that was handed out stays handed out.

    Supplying ``dtcr_matching_bytes`` runs the same enrichment the SECR
    Management page performs: Reason for Change, DTCR numbers and bulletin
    numbers are filled from the DTCR Matching Report, the per-DTCR rows are
    stored, and each DTCR is assigned to the connector (CNUM) it belongs to.
    Enrichment failing never loses the SECR — the unenriched workbook is still
    generated and stored, with the reason recorded as a warning.
    """
    if not plan.can_generate:
        raise SpliceInputError(
            "The SECR metadata must be resolved before generating: "
            + "; ".join(plan.problems)
        )

    metadata = plan.metadata
    sequence_number = secr_db.reserve_next_secr_number(
        metadata.model_year, metadata.phase, db_path=db_path
    )
    secr_number = build_secr_number(metadata, plan.change_type, sequence_number)
    filename = build_filename(
        metadata, plan.change_type, sequence_number, 1, plan.generation_date
    )
    logger.info("Reserved SECR number %s for %s", sequence_number, secr_number)

    secr_bytes, _meta = create_secr_bytes(
        def_bytes=def_bytes,
        def_filename=def_filename,
        reason_for_change=reason_for_change,
        secr_author=secr_author,
        design_release_engineer=design_release_engineer,
        change_requested_by=change_requested_by,
        original_issue_date=original_issue_date,
        reissue_date="",
        version="1",
        phase_implemented=phase_implemented,
        pull_ahead=pull_ahead,
        secr_change_type=plan.change_type,
        secr_sequence=sequence_number,
        secr_model_year=metadata.model_year,
        secr_program=metadata.program,
        secr_phase=metadata.phase,
        secr_number_override=secr_number,
        filename_override=filename,
        summary_overrides=metadata.as_dict(),
    )

    secr_bytes, mapping_df, summary_df, enrich_warnings = _enrich(
        secr_bytes, dtcr_matching_bytes, filename
    )

    secr_id, change_count, warnings, assignments = _store(
        secr_bytes,
        filename=filename,
        action="create",
        plan_metadata=metadata,
        change_type=plan.change_type,
        sequence_number=sequence_number,
        version_number=1,
        generation_date=plan.generation_date,
        def_filename=def_filename,
        old_def_source=plan.old_def_source,
        new_def_source=plan.new_def_source,
        sources=plan.sources,
        parent_secr_number=None,
        dtcr_mapping_df=mapping_df,
        db_path=db_path,
    )
    return GeneratedSecr(
        secr_bytes=secr_bytes,
        filename=filename,
        secr_number=secr_number,
        identity=identity_from_metadata(metadata, sequence_number),
        version_number=1,
        secr_id=secr_id,
        change_count=change_count,
        metadata=metadata,
        warnings=warnings + enrich_warnings,
        enriched=mapping_df is not None,
        enrichment_summary=summary_df,
        dtcr_assignments=assignments,
    )


def _enrich(
    secr_bytes: bytes, dtcr_matching_bytes: Optional[bytes], filename: str
):
    """Apply a DTCR Matching Report to a freshly generated SECR.

    Runs :func:`secrdb.core.secr.numbering.auto_enrich_secr` — the same call the SECR
    Management page makes — and returns the enriched workbook plus the mapping
    used. On failure the original workbook is returned unchanged along with the
    reason, so a bad or mismatched report can never cost the engineer the SECR.
    """
    if not dtcr_matching_bytes:
        return secr_bytes, None, None, []
    try:
        enriched_bytes, _meta, mapping_df, summary_df, family = auto_enrich_secr(
            secr_bytes, dtcr_matching_bytes, filename
        )
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        logger.warning("SECR enrichment skipped for %s: %s", filename, exc)
        return (
            secr_bytes,
            None,
            None,
            [
                f"The SECR was generated but NOT enriched: {exc}. "
                "Re-run enrichment with a matching DTCR report."
            ],
        )
    logger.info("Enriched %s against harness family %s", filename, family)

    # A report can load cleanly and still have nothing for this SECR's harness
    # family, which would leave Reason for Change / DTCR # / Bulletin # blank.
    # Say so rather than hand back a quietly empty enrichment.
    warnings: List[str] = []
    matched = filter_dtcr_mapping_for_family(mapping_df, family)
    if len(matched) == 0:
        warnings.append(
            f"The DTCR Matching Report has no Complete/Draft rows for harness "
            f"family '{family}', so Reason for Change, DTCR # and Bulletin # "
            "were left empty. Check that the report covers this harness."
        )
    return enriched_bytes, mapping_df, summary_df, warnings


# ---------------------------------------------------------------------------
# Update Existing SECR
# ---------------------------------------------------------------------------

def _metadata_from_record(record: Dict[str, Any]) -> SecrMetadata:
    return SecrMetadata(
        harness_family=str(record.get("harness_family") or "").upper(),
        model_year=str(record.get("model_year") or ""),
        phase=str(record.get("phase") or ""),
        program=str(record.get("program") or "").upper(),
    )


def _comparable(metadata: SecrMetadata) -> SecrMetadata:
    """Normalize for comparison: 2-digit model year, phase without revision."""
    year, phase = scope_key(metadata.model_year, metadata.phase)
    return SecrMetadata(
        harness_family=metadata.harness_family.upper(),
        model_year=year,
        phase=phase,
        program=metadata.program.upper(),
    )


def plan_secr_update(
    secr_id: int,
    def_bytes: bytes,
    def_filename: str,
    *,
    when: Optional[date] = None,
    db_path: Optional[Path] = None,
) -> UpdateSecrPlan:
    """Work out the next version of an existing generated SECR.

    Compares the scope of the new DEF against the SECR being updated. Matching
    scope means the same number and the next version. A changed Harness Family,
    Model Year, Phase or Program does **not** silently become a new version —
    the plan comes back blocked with the differences spelled out.
    """
    record = secr_db.get_secr(secr_id, db_path=db_path)
    if record is None:
        raise SpliceInputError(f"SECR record #{secr_id} is not in the database.")
    if record.get("secr_sequence_number") is None:
        raise SpliceInputError(
            f"SECR {record.get('secr_number')} was imported, not generated here. "
            "Automatic numbering and versioning apply only to generated SECRs."
        )

    identity = SecrIdentity(
        model_year=str(record["scope_model_year"]),
        phase=str(record["scope_phase"]),
        sequence_number=int(record["secr_sequence_number"]),
    )
    versions = secr_db.get_versions(
        identity.model_year, identity.phase, identity.sequence_number, db_path=db_path
    )
    current_version = max(
        (int(v["version_number"] or 0) for v in versions), default=0
    )

    extracted = extract_metadata_from_def(def_bytes, def_filename)
    new_metadata = extracted.metadata
    existing_metadata = _metadata_from_record(record)
    change_type = str(record.get("change_type") or CHANGE_TYPE_DESIGN)

    problems = validate_metadata(new_metadata, change_type)
    if extracted.read_error:
        problems.insert(0, extracted.read_error)
    differences = compare_metadata(
        _comparable(existing_metadata), _comparable(new_metadata)
    )

    next_version = current_version + 1
    when = when or date.today()
    secr_number = ""
    filename = ""
    if not problems and not changed_fields(differences):
        secr_number = build_secr_number(
            existing_metadata, change_type, identity.sequence_number
        )
        filename = build_filename(
            existing_metadata,
            change_type,
            identity.sequence_number,
            next_version,
            when,
        )

    return UpdateSecrPlan(
        identity=identity,
        existing=record,
        existing_metadata=existing_metadata,
        new_metadata=new_metadata,
        differences=differences,
        change_type=change_type,
        current_version=current_version,
        next_version=next_version,
        generation_date=when,
        secr_number=secr_number,
        filename=filename,
        notes=list(extracted.notes),
        warnings=list(extracted.warnings),
        problems=problems,
        old_def_source=extracted.old_def_source,
        new_def_source=extracted.new_def_source,
    )


def generate_secr_update(
    def_bytes: bytes,
    def_filename: str,
    old_secr_bytes: bytes,
    plan: UpdateSecrPlan,
    *,
    subject: str = "",
    secr_author: str = "",
    design_release_engineer: str = "",
    change_requested_by: str = "",
    reissue_date: str = "",
    phase_implemented: str = "",
    pull_ahead: str = "",
    dtcr_matching_bytes: Optional[bytes] = None,
    db_path: Optional[Path] = None,
) -> GeneratedSecr:
    """Generate the next version of an existing SECR. Keeps the same number.

    The previous version is left untouched — it is a separate row with its own
    workbook copy. A DTCR Matching Report may be supplied here too, so a
    revision re-enriches against the current report.
    """
    if plan.scope_changed:
        raise SecrScopeChanged(plan.identity, plan.differences)
    if not plan.can_generate:
        raise SpliceInputError(
            "The SECR metadata must be resolved before generating: "
            + "; ".join(plan.problems)
        )

    metadata = plan.existing_metadata
    version_number = plan.next_version
    secr_number = build_secr_number(
        metadata, plan.change_type, plan.identity.sequence_number
    )
    filename = build_filename(
        metadata,
        plan.change_type,
        plan.identity.sequence_number,
        version_number,
        plan.generation_date,
    )

    secr_bytes, _meta = update_secr_bytes(
        def_bytes=def_bytes,
        def_filename=def_filename,
        old_secr_bytes=old_secr_bytes,
        subject=subject,
        secr_author=secr_author,
        design_release_engineer=design_release_engineer,
        change_requested_by=change_requested_by,
        reissue_date=reissue_date,
        version=str(version_number),
        phase_implemented=phase_implemented,
        pull_ahead=pull_ahead,
        secr_change_type=plan.change_type,
        secr_sequence=plan.identity.sequence_number,
        secr_model_year=metadata.model_year,
        secr_program=metadata.program,
        secr_phase=metadata.phase,
        secr_number_override=secr_number,
        filename_override=filename,
        summary_overrides=metadata.as_dict(),
    )

    secr_bytes, mapping_df, summary_df, enrich_warnings = _enrich(
        secr_bytes, dtcr_matching_bytes, filename
    )

    secr_id, change_count, warnings, assignments = _store(
        secr_bytes,
        filename=filename,
        action="update",
        plan_metadata=metadata,
        change_type=plan.change_type,
        sequence_number=plan.identity.sequence_number,
        version_number=version_number,
        generation_date=plan.generation_date,
        def_filename=def_filename,
        old_def_source=plan.old_def_source,
        new_def_source=plan.new_def_source,
        sources={},
        parent_secr_number=str(plan.existing.get("secr_number") or ""),
        dtcr_mapping_df=mapping_df,
        db_path=db_path,
    )
    return GeneratedSecr(
        secr_bytes=secr_bytes,
        filename=filename,
        secr_number=secr_number,
        identity=plan.identity,
        version_number=version_number,
        secr_id=secr_id,
        change_count=change_count,
        metadata=metadata,
        warnings=warnings + enrich_warnings,
        enriched=mapping_df is not None,
        enrichment_summary=summary_df,
        dtcr_assignments=assignments,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _store(
    secr_bytes: bytes,
    *,
    filename: str,
    action: str,
    plan_metadata: SecrMetadata,
    change_type: str,
    sequence_number: int,
    version_number: int,
    generation_date: date,
    def_filename: str,
    old_def_source: str,
    new_def_source: str,
    sources: Dict[str, str],
    parent_secr_number: Optional[str],
    db_path: Optional[Path],
    dtcr_mapping_df=None,
) -> tuple[int, int, List[str], List[DtcrAssignment]]:
    """Persist a generated SECR with its identity, provenance and source file."""
    record = secr_db.record_from_workbook(
        secr_bytes,
        action=action,
        source_def_filename=def_filename,
        filename=filename,
        change_type=change_type,
        parent_secr_number=parent_secr_number,
        enriched=dtcr_mapping_df is not None,
        dtcr_mapping_df=dtcr_mapping_df,
    )
    assignments = assign_dtcrs_to_cnums(record.get("changes", []), dtcr_mapping_df)
    scope_year, scope_phase = scope_key(
        plan_metadata.model_year, plan_metadata.phase
    )
    record.update(
        {
            "import_origin": secr_db.ORIGIN_GENERATED,
            "secr_sequence_number": int(sequence_number),
            "scope_model_year": scope_year,
            "scope_phase": scope_phase,
            "version_number": int(version_number),
            "generation_date": format_generation_date(generation_date),
            "old_def_source": old_def_source,
            "new_def_source": new_def_source,
            "metadata_provenance": "; ".join(
                f"{key}={value}" for key, value in sorted(sources.items())
            ),
        }
    )
    secr_id = secr_db.save_secr(
        record,
        db_path,
        on_conflict=secr_db.CONFLICT_ERROR,
        source_bytes=secr_bytes,
    )
    warnings = [
        line for line in (record.get("parse_warnings") or "").split("\n") if line
    ]
    return secr_id, len(record.get("changes", [])), warnings, assignments
