"""Tests for issue recording and export.

The governing rule: diagnostics must never be the reason something breaks. A
field-test build that crashes while recording a crash is worse than one that
records nothing, so every path here is checked for "degrades quietly".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from secrdb import diagnostics


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch) -> Path:
    """Point diagnostics at a throwaway directory, never the real one."""
    monkeypatch.setattr(diagnostics, "DATA_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def test_an_error_is_recorded_with_its_traceback() -> None:
    try:
        raise ValueError("circuit not found")
    except ValueError as exc:
        issue = diagnostics.record_error(exc, where="browse")

    assert issue.kind == diagnostics.KIND_ERROR
    assert "ValueError: circuit not found" in issue.summary
    assert "Traceback" in issue.detail
    assert issue.where == "browse"
    assert issue.app_version == diagnostics.APP_VERSION

    stored = diagnostics.load_issues()
    assert len(stored) == 1
    assert stored[0]["issue_id"] == issue.issue_id


def test_an_unanswered_question_is_recorded_with_the_tools_tried() -> None:
    issue = diagnostics.record_unanswered(
        "which harness changed most in MY30?",
        reason="no data for that model year",
        tools_called=[{"name": "get_change_counts", "arguments": {}}],
    )

    assert issue.kind == diagnostics.KIND_UNANSWERED
    assert issue.summary.startswith("which harness")
    assert issue.context["tools_called"][0]["name"] == "get_change_counts"


def test_user_feedback_is_recorded() -> None:
    diagnostics.record_feedback("the import said 0 files", where="import")
    stored = diagnostics.load_issues()
    assert stored[0]["kind"] == diagnostics.KIND_FEEDBACK
    assert stored[0]["where"] == "import"


def test_issues_accumulate_in_order() -> None:
    for index in range(5):
        diagnostics.record_feedback(f"note {index}")
    stored = diagnostics.load_issues()
    assert [issue["summary"] for issue in stored] == [f"note {i}" for i in range(5)]


def test_each_line_is_independently_parseable(isolated_data_dir: Path) -> None:
    """JSONL, so a half-written file still yields everything before the break."""
    diagnostics.record_feedback("first")
    diagnostics.record_feedback("second")
    lines = diagnostics.issues_path().read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)


def test_a_corrupt_line_is_skipped_not_fatal(isolated_data_dir: Path) -> None:
    diagnostics.record_feedback("good")
    with diagnostics.issues_path().open("a") as handle:
        handle.write("{ this is not json\n")
    diagnostics.record_feedback("also good")

    stored = diagnostics.load_issues()
    assert [issue["summary"] for issue in stored] == ["good", "also good"]


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def test_recording_never_raises(monkeypatch, tmp_path: Path) -> None:
    """Even if the directory is unwritable, the app carries on."""
    monkeypatch.setattr(diagnostics, "DATA_DIR", tmp_path / "nope" / "deeper")
    monkeypatch.setattr(
        diagnostics.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("ro"))
    )
    issue = diagnostics.record_feedback("still returns")
    assert issue.summary == "still returns"


def test_binary_context_is_never_stored() -> None:
    diagnostics.record_feedback("upload failed", context={"file": b"\x00\x01\x02"})
    stored = diagnostics.load_issues()[0]
    assert stored["context"]["file"] == "<3 bytes>"


def test_unserialisable_context_degrades_to_text() -> None:
    diagnostics.record_feedback("odd", context={"path": Path("/tmp/x")})
    stored = diagnostics.load_issues()[0]
    assert isinstance(stored["context"]["path"], str)


def test_a_huge_detail_is_truncated() -> None:
    issue = diagnostics.record(diagnostics.KIND_ERROR, "big", detail="x" * 50_000)
    assert len(issue.detail) < 9_000
    assert "truncated" in issue.detail


def test_the_log_is_capped(monkeypatch) -> None:
    monkeypatch.setattr(diagnostics, "MAX_ISSUES", 10)
    for index in range(25):
        diagnostics.record_feedback(f"note {index}")
    stored = diagnostics.load_issues()
    assert len(stored) <= 10
    assert stored[-1]["summary"] == "note 24"  # newest kept


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def test_export_contains_environment_and_issues() -> None:
    diagnostics.record_feedback("something odd")
    payload = json.loads(diagnostics.export_bytes(note="please look at this"))

    assert payload["user_note"] == "please look at this"
    assert payload["issue_total"] == 1
    assert payload["issue_counts"]["feedback"] == 1
    assert payload["issues"][0]["summary"] == "something odd"

    environment = payload["environment"]
    assert environment["app_version"] == diagnostics.APP_VERSION
    assert environment["python"]
    assert environment["platform"]
    assert "streamlit" in environment


def test_export_is_valid_json_when_there_is_nothing_to_report() -> None:
    payload = json.loads(diagnostics.export_bytes())
    assert payload["issue_total"] == 0
    assert payload["issues"] == []
    assert payload["environment"]  # still worth sending


def test_export_filename_is_dated_and_safe() -> None:
    name = diagnostics.export_filename()
    assert name.startswith("SECR_Database_issue_report_")
    assert name.endswith(".json")
    assert " " not in name


def test_database_state_reports_a_missing_database() -> None:
    state = diagnostics.database_state()
    assert state["database_exists"] in (True, False)


def test_clearing_removes_the_log() -> None:
    diagnostics.record_feedback("one")
    diagnostics.record_feedback("two")
    assert diagnostics.clear_issues() == 2
    assert diagnostics.load_issues() == []
