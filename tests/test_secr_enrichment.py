"""Tests for DTCR enrichment and DTCR → CNUM assignment during generation.

Generating a SECR with a DTCR Matching Report must do what the SECR Management
page does — fill Reason for Change, DTCR # and Bulletin # — and additionally
attach each DTCR to the connector (CNUM) it was matched to, so the change
records become searchable by DTCR.
"""

from __future__ import annotations

import io
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from splice.secr import api, db as secr_db, generation
from splice.secr.generation import assign_dtcrs_to_cnums, build_cnum_dtcr_map
from tests.test_secr_identity import build_def_compare, def_filename


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "enrichment_test.db"


def build_matching_report(rows: list[dict]) -> bytes:
    """A DTCR Matching Report workbook in the shape the loader expects."""
    columns = [
        "DTCR#", "Device Transmittal", "Extracted Device Control Number",
        "Reason for change", "Status", "Match Method", "Matched DTx Value",
        "CNUM", "Harness Family",
    ]
    frame = pd.DataFrame(
        [{column: row.get(column, "") for column in columns} for row in rows]
    )
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="DTCR_Harness_Family_Mapping", index=False)
    return buffer.getvalue()


#: The DEF fixture's Connector sheet carries CNUM "SD401" on an IP harness.
MATCHING_ROWS = [
    {
        "DTCR#": "49754",
        "Device Transmittal": "59282-Connector",
        "Reason for change": "CHANGE CONNECTOR PART NUMBER. Bulletin 320767",
        "Status": "Complete",
        "Match Method": "Device Name",
        "CNUM": "SD401",
        "Harness Family": "IP",
    },
    {
        "DTCR#": "50319",
        "Device Transmittal": "11430-Inline",
        "Reason for change": "Update wireless charge release codes",
        "Status": "Complete",
        "Match Method": "Device Name",
        "CNUM": "SD401, D2996B",
        "Harness Family": "IP",
    },
    {
        "DTCR#": "49736",
        "Device Transmittal": "59282-Battery",
        "Reason for change": "Removal of aux battery",
        "Status": "Deleted",
        "Match Method": "Device Name",
        "CNUM": "X350A",
        "Harness Family": "IP",
    },
    {
        "DTCR#": "50311",
        "Device Transmittal": "112994-Seat",
        "Reason for change": "Seat belt reminder",
        "Status": "Complete",
        "Match Method": "Device Name",
        "CNUM": "None",
        "Harness Family": "SEAT_3RD_ROW_RIGHT",
    },
]


# ---------------------------------------------------------------------------
# CNUM map
# ---------------------------------------------------------------------------

def test_cnum_map_splits_multi_cnum_cells() -> None:
    frame = pd.DataFrame(MATCHING_ROWS)
    mapping = build_cnum_dtcr_map(frame)

    assert set(mapping) == {"SD401", "D2996B", "X350A"}
    assert [e["dtcr_number"] for e in mapping["SD401"]] == ["49754", "50319"]
    assert mapping["D2996B"][0]["dtcr_number"] == "50319"


def test_cnum_map_skips_rows_without_a_connector() -> None:
    mapping = build_cnum_dtcr_map(pd.DataFrame(MATCHING_ROWS))
    assert all("SEAT" not in cnum for cnum in mapping)
    assert "NONE" not in mapping


def test_cnum_map_is_empty_without_a_cnum_column() -> None:
    frame = pd.DataFrame([{"DTCR#": "1", "Harness Family": "IP"}])
    assert build_cnum_dtcr_map(frame) == {}
    assert build_cnum_dtcr_map(None) == {}


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

def test_dtcrs_are_assigned_to_their_cnum_changes() -> None:
    changes = [
        {"object_type": "connector", "object_id": "SD401", "dtcr_number": None},
        {"object_type": "connector", "object_id": "SD401", "dtcr_number": None},
    ]
    assignments = assign_dtcrs_to_cnums(changes, pd.DataFrame(MATCHING_ROWS))

    assert [c["dtcr_number"] for c in changes] == ["49754, 50319"] * 2
    assert len(assignments) == 1
    assert assignments[0].cnum == "SD401"
    assert assignments[0].change_count == 2
    assert assignments[0].source == "DTCR Matching Report"


def test_a_dtcr_named_in_the_se_comment_is_not_overwritten() -> None:
    changes = [
        {"object_type": "connector", "object_id": "SD401", "dtcr_number": "99999"}
    ]
    assignments = assign_dtcrs_to_cnums(changes, pd.DataFrame(MATCHING_ROWS))

    assert changes[0]["dtcr_number"] == "99999"
    assert assignments[0].source == "SE comment"


def test_unmapped_and_non_connector_changes_are_untouched() -> None:
    changes = [
        {"object_type": "connector", "object_id": "UNKNOWN", "dtcr_number": None},
        {"object_type": "circuit", "object_id": "SD401", "dtcr_number": None},
    ]
    assert assign_dtcrs_to_cnums(changes, pd.DataFrame(MATCHING_ROWS)) == []
    assert all(c["dtcr_number"] is None for c in changes)


def test_assignment_without_a_report_does_nothing() -> None:
    changes = [{"object_type": "connector", "object_id": "SD401", "dtcr_number": None}]
    assert assign_dtcrs_to_cnums(changes, None) == []
    assert changes[0]["dtcr_number"] is None


# ---------------------------------------------------------------------------
# Generation with a DTCR Matching Report
# ---------------------------------------------------------------------------

def _generate(
    db_path: Path, report: bytes | None, *, se_comment: str = "DTCR 50319"
) -> generation.GeneratedSecr:
    """Generate a SECR. ``se_comment`` controls whether the connector row
    already names a DTCR, which is what decides SE-comment-wins."""
    payload = build_def_compare(connector_se_comment=se_comment)
    name = def_filename()
    plan = generation.plan_new_secr(
        payload, name, "Design Change", db_path=db_path
    )
    return generation.generate_new_secr(
        payload, name, plan, dtcr_matching_bytes=report, db_path=db_path
    )


def test_generating_with_a_report_enriches_the_workbook(db_path: Path) -> None:
    result = _generate(db_path, build_matching_report(MATCHING_ROWS))

    assert result.enriched
    summary = openpyxl.load_workbook(
        io.BytesIO(result.secr_bytes), data_only=True
    )["Summary"]
    assert "49754" in str(summary["C14"].value)
    assert "320767" in str(summary["G14"].value)
    assert "49754" in str(summary["B17"].value)


def test_a_cnum_with_no_se_comment_gets_the_mapped_dtcrs(db_path: Path) -> None:
    result = _generate(
        db_path, build_matching_report(MATCHING_ROWS), se_comment=""
    )

    assert result.dtcr_assignments
    assigned = {a.cnum: a.dtcr_number for a in result.dtcr_assignments}
    assert assigned["SD401"] == "49754, 50319"

    stored = secr_db.get_secr(result.secr_id, db_path=db_path)
    connector_changes = [
        c for c in stored["changes"] if c["object_id"] == "SD401"
    ]
    assert connector_changes
    assert all(c["dtcr_number"] == "49754, 50319" for c in connector_changes)


def test_an_se_comment_on_the_row_still_wins_during_generation(
    db_path: Path,
) -> None:
    """What the engineer wrote on the row outranks the report's CNUM match."""
    result = _generate(
        db_path, build_matching_report(MATCHING_ROWS), se_comment="DTCR 50319"
    )

    stored = secr_db.get_secr(result.secr_id, db_path=db_path)
    connector_changes = [
        c for c in stored["changes"] if c["object_id"] == "SD401"
    ]
    assert all(c["dtcr_number"] == "50319" for c in connector_changes)
    assert [a.source for a in result.dtcr_assignments] == ["SE comment"]


def test_assigned_dtcrs_are_queryable(db_path: Path) -> None:
    """The point of the assignment: find the change by its DTCR afterwards."""
    _generate(db_path, build_matching_report(MATCHING_ROWS), se_comment="")

    changes = secr_db.find_changes(dtcr_number="49754, 50319", db_path=db_path)
    assert changes and changes[0]["object_id"] == "SD401"


def test_the_secr_is_findable_by_a_mapped_dtcr_either_way(db_path: Path) -> None:
    """Even when the SE comment wins on the row, the report's DTCRs are stored
    as per-SECR rows, so searching for one still finds the SECR."""
    _generate(db_path, build_matching_report(MATCHING_ROWS), se_comment="DTCR 50319")

    assert api.search_secrs(dtcr="49754", db_path=db_path)
    assert api.search_secrs(dtcr="50319", db_path=db_path)


def test_per_dtcr_rows_are_stored_for_the_secr_family(db_path: Path) -> None:
    result = _generate(db_path, build_matching_report(MATCHING_ROWS))
    stored = secr_db.get_secr(result.secr_id, db_path=db_path)

    numbers = {row["dtcr_number"] for row in stored["dtcrs"]}
    assert {"49754", "50319"} <= numbers
    # A different harness family's DTCR is not attached to this SECR.
    assert "50311" not in numbers
    assert stored["enriched"] == 1


def test_generating_without_a_report_still_works(db_path: Path) -> None:
    result = _generate(db_path, None)

    assert not result.enriched
    assert result.dtcr_assignments == []
    assert result.change_count > 0
    stored = secr_db.get_secr(result.secr_id, db_path=db_path)
    assert stored["dtcrs"] == []
    assert stored["enriched"] == 0


def test_an_unreadable_report_never_costs_the_engineer_the_secr(
    db_path: Path,
) -> None:
    result = _generate(db_path, b"not a workbook")

    assert not result.enriched
    assert any("NOT enriched" in warning for warning in result.warnings)
    assert secr_db.get_secr(result.secr_id, db_path=db_path) is not None
    assert result.change_count > 0


def test_a_report_matching_no_family_is_reported_not_silent(
    db_path: Path,
) -> None:
    """A report that loads fine but covers no matching harness must say so.

    It would otherwise leave Reason for Change / DTCR # / Bulletin # blank with
    no indication that anything was wrong.
    """
    report = build_matching_report(
        [dict(MATCHING_ROWS[3])]  # SEAT family only; this SECR is IP
    )
    result = _generate(db_path, report)

    assert any("no Complete/Draft rows" in warning for warning in result.warnings)
    assert any("'IP'" in warning for warning in result.warnings)
    assert result.dtcr_assignments == []
    assert secr_db.get_secr(result.secr_id, db_path=db_path) is not None


def test_an_update_can_re_enrich_against_the_report(db_path: Path) -> None:
    report = build_matching_report(MATCHING_ROWS)
    first = _generate(db_path, None)
    assert not first.enriched

    payload, name = build_def_compare(), def_filename()
    plan = generation.plan_secr_update(
        first.secr_id, payload, name, db_path=db_path
    )
    second = generation.generate_secr_update(
        payload,
        name,
        first.secr_bytes,
        plan,
        dtcr_matching_bytes=report,
        db_path=db_path,
    )

    assert second.enriched
    assert second.version_number == 2
    assert {a.cnum for a in second.dtcr_assignments} == {"SD401"}
