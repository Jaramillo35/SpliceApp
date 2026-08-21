"""Generating several SECRs from several DEF compares in one pass.

Driven by two field reports: uploading a second compare left the previous
SECR's result on screen — so it looked as though nothing had happened, and
pressing Generate again issued another number — and a set of compares in one
scope has to preview distinct numbers rather than showing every file the same
one.

Nothing here imports the Streamlit page: the page runs on import, and the
logic under test is deliberately independent of it.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from secrdb.core.secr import batch, db as secr_db
from secrdb.core.secr.identity import CHANGE_TYPE_DESIGN

from tests.test_core_identity import build_def_compare, def_filename


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "batch.db"


def _files(*harnesses: str):
    return [
        (def_filename(harness=harness), build_def_compare(harness=harness))
        for harness in harnesses
    ]


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def test_each_compare_in_one_scope_previews_its_own_number(db_path: Path) -> None:
    """Peeking per file would show every SECR in a scope the same number."""
    planned = batch.plan_batch(
        _files("IP", "BODY_LEFT", "DASH"), CHANGE_TYPE_DESIGN, db_path=db_path
    )

    assert [item.number for item in planned] == [1000, 1001, 1002]
    assert all(item.ready for item in planned)


def test_separate_scopes_each_start_at_1000(db_path: Path) -> None:
    files = [
        (def_filename(phase="X1"), build_def_compare()),
        (def_filename(phase="X2"), build_def_compare(new_phase="X2_A")),
        (def_filename(phase="X1", harness="DASH"), build_def_compare(harness="DASH")),
    ]

    planned = batch.plan_batch(files, CHANGE_TYPE_DESIGN, db_path=db_path)

    assert [item.number for item in planned] == [1000, 1000, 1001]


def test_projection_continues_from_what_is_already_issued(db_path: Path) -> None:
    batch.generate_batch(
        batch.plan_batch(_files("IP"), CHANGE_TYPE_DESIGN, db_path=db_path),
        db_path=db_path,
    )

    planned = batch.plan_batch(
        _files("BODY_LEFT", "DASH"), CHANGE_TYPE_DESIGN, db_path=db_path
    )

    assert [item.number for item in planned] == [1001, 1002]


def test_an_unreadable_compare_is_reported_not_fatal(db_path: Path) -> None:
    """One bad file must not hide the good ones."""
    files = _files("IP") + [("broken.xlsx", b"not a workbook")]

    planned = batch.plan_batch(files, CHANGE_TYPE_DESIGN, db_path=db_path)

    assert planned[0].ready and planned[0].number == 1000
    assert not planned[1].ready
    assert "could not be read" in planned[1].plan.problems[0]


def test_a_blocked_compare_consumes_no_number(db_path: Path) -> None:
    files = [
        ("mystery.xlsx", build_def_compare(include_identifiers=False)),
    ] + _files("IP")

    planned = batch.plan_batch(files, CHANGE_TYPE_DESIGN, db_path=db_path)

    assert planned[0].number is None
    assert planned[1].number == 1000


def test_planning_reserves_nothing(db_path: Path) -> None:
    batch.plan_batch(_files("IP", "DASH"), CHANGE_TYPE_DESIGN, db_path=db_path)
    batch.plan_batch(_files("IP", "DASH"), CHANGE_TYPE_DESIGN, db_path=db_path)

    assert secr_db.peek_next_secr_number("2028", "X1", db_path=db_path) == 1000


# ---------------------------------------------------------------------------
# The stale-result signature
# ---------------------------------------------------------------------------

def test_the_signature_changes_with_the_uploads() -> None:
    """This is what makes a new upload clear the previous SECR."""
    one = _files("IP")
    two = _files("IP", "DASH")

    assert batch.signature_for(one, "Design Change") == batch.signature_for(
        one, "Design Change"
    )
    assert batch.signature_for(one, "Design Change") != batch.signature_for(
        two, "Design Change"
    )
    assert batch.signature_for(one, "Design Change") != batch.signature_for(
        one, "Miscellaneous"
    )


def test_the_signature_changes_when_a_file_is_replaced() -> None:
    """Same filename, different content — the case that looked like a no-op."""
    first = [("compare.xlsx", build_def_compare(harness="IP"))]
    second = [("compare.xlsx", build_def_compare(harness="DASH"))]

    assert batch.signature_for(first, "Design Change") != batch.signature_for(
        second, "Design Change"
    )


# ---------------------------------------------------------------------------
# Generating
# ---------------------------------------------------------------------------

def test_a_batch_issues_consecutive_numbers(db_path: Path) -> None:
    planned = batch.plan_batch(
        _files("IP", "BODY_LEFT", "DASH"), CHANGE_TYPE_DESIGN, db_path=db_path
    )

    outcome = batch.generate_batch(planned, db_path=db_path)

    assert outcome.ok
    assert [r.identity.sequence_number for r in outcome.results] == [
        1000, 1001, 1002,
    ]
    assert len({r.secr_number for r in outcome.results}) == 3


def test_the_shared_details_reach_every_secr(db_path: Path) -> None:
    """Entered once, applied to all — the point of the batch form."""
    shared = {
        "reason_for_change": "28 X1 release",
        "secr_author": "M. Aguilar",
        "design_release_engineer": "Ken Kopf",
        "change_requested_by": "STELLANTIS",
        "original_issue_date": "08/14/2026",
        "phase_implemented": "X1",
        "pull_ahead": "N",
    }
    planned = batch.plan_batch(
        _files("IP", "DASH"), CHANGE_TYPE_DESIGN, db_path=db_path
    )

    outcome = batch.generate_batch(planned, shared, db_path=db_path)

    assert len(outcome.results) == 2
    for result in outcome.results:
        record = secr_db.get_secr(result.secr_id, db_path=db_path)
        assert record["secr_author"] == "M. Aguilar"
        assert record["design_release_engineer"] == "Ken Kopf"
        assert record["change_requested_by"] == "STELLANTIS"
        assert record["original_issue_date"] == "08/14/2026"
        assert record["phase_implemented"] == "X1"


def test_blocked_compares_are_skipped_not_generated(db_path: Path) -> None:
    files = _files("IP") + [("broken.xlsx", b"not a workbook")]
    planned = batch.plan_batch(files, CHANGE_TYPE_DESIGN, db_path=db_path)

    outcome = batch.generate_batch(planned, db_path=db_path)

    assert len(outcome.results) == 1
    assert outcome.failures == []          # blocked != failed
    assert secr_db.peek_next_secr_number("2028", "X1", db_path=db_path) == 1001


def test_progress_is_reported_for_each_file(db_path: Path) -> None:
    seen = []
    planned = batch.plan_batch(
        _files("IP", "DASH"), CHANGE_TYPE_DESIGN, db_path=db_path
    )

    batch.generate_batch(
        planned, on_progress=lambda fraction, name: seen.append((fraction, name)),
        db_path=db_path,
    )

    assert [name for _fraction, name in seen] == [item.name for item in planned]
    assert seen[-1][0] == 1.0


def test_an_empty_batch_is_harmless(db_path: Path) -> None:
    outcome = batch.generate_batch([], db_path=db_path)
    assert outcome.results == [] and outcome.failures == []
    assert not outcome.ok


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------

def test_the_zip_holds_every_generated_workbook(db_path: Path) -> None:
    outcome = batch.generate_batch(
        batch.plan_batch(_files("IP", "BODY_LEFT"), CHANGE_TYPE_DESIGN,
                         db_path=db_path),
        db_path=db_path,
    )

    archive = zipfile.ZipFile(io.BytesIO(batch.zip_results(outcome.results)))

    assert sorted(archive.namelist()) == sorted(
        result.filename for result in outcome.results
    )
    assert all(archive.read(name)[:2] == b"PK" for name in archive.namelist())
