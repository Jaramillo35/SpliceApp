"""The applicability export, and the cleanup notes it carries.

A ticked row must reach the workbook as a written instruction — the point of
the Complexity Cleanup Notes column is that someone can act on it without the
workbench open.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).parent))

from fixtures_dtxcircuits import circuit_rows, harnesses  # noqa: E402
from splice.dtxcircuits import analyze, report  # noqa: E402


@pytest.fixture()
def entries():
    return [report.Entry(label=f"{a.harness} → {a.harness}", family=a.harness,
                         filename=f"{a.harness}.xlsm", analysis=a)
            for a in analyze(circuit_rows(), harnesses())]


@pytest.fixture()
def body_left(entries):
    return next(e for e in entries if e.family == "BODY_LEFT")


class TestItemKey:
    def test_key_is_stable_and_distinguishes_kinds(self):
        a = report.item_key("IP", "IP", report.KIND_CIRCUIT, "CKT_1")
        b = report.item_key("IP", "IP", report.KIND_CONNECTOR, "CKT_1")
        assert a == report.item_key("IP", "IP", report.KIND_CIRCUIT, "CKT_1")
        assert a != b

    def test_same_ident_on_two_harnesses_is_two_keys(self):
        # one DTx family may map to several harnesses; a circuit selected on
        # one must not silently select it on the other
        assert report.item_key("IP", "LEFT", "circuit", "CKT_1") != \
            report.item_key("IP", "RIGHT", "circuit", "CKT_1")


class TestNotes:
    def test_never_built_note_states_the_condition_and_the_two_causes(self, body_left):
        s = report.selection_for(body_left, report.KIND_CIRCUIT, "CKT_500")
        assert "No build of BODY_LEFT" in s.note
        assert "(CCC)" in s.note
        assert "missing a code" in s.note
        assert s.verdict == "never built"

    def test_untracked_note_names_the_code(self, body_left):
        s = report.selection_for(body_left, report.KIND_CIRCUIT, "CKT_600")
        assert "ZZZ" in s.note and "not tracked" in s.note

    def test_gap_note_lists_the_circuits_resting_on_it(self, body_left):
        s = report.selection_for(body_left, report.KIND_GAP, "ZZZ")
        assert "CKT_600" in s.note and s.verdict == "sales-code gap"

    def test_variant_note_reports_the_split(self, body_left):
        s = report.selection_for(body_left, report.KIND_CIRCUIT, "CKT_200")
        assert "2 of 4 builds" in s.note

    def test_unknown_item_returns_none(self, body_left):
        assert report.selection_for(body_left, report.KIND_CIRCUIT, "NOPE") is None
        assert report.selection_for(body_left, "nonsense", "CKT_500") is None


class TestWorkbook:
    def _book(self, entries, cleanup):
        data = report.build_report(entries, cleanup, dtx_program="2030QX",
                                   dtx_phase="V1_A")
        return load_workbook(io.BytesIO(data))

    def test_every_sheet_is_present(self, entries):
        wb = self._book(entries, {})
        assert wb.sheetnames == ["Read Me", "Circuits", "Connectors",
                                 "Sales-code gaps", "Complexity Cleanup"]

    def test_cleanup_column_is_named_exactly(self, entries):
        wb = self._book(entries, {})
        for sheet in ("Circuits", "Connectors", "Sales-code gaps"):
            headers = [c.value for c in wb[sheet][1]]
            assert report.CLEANUP_COLUMN in headers, sheet
        assert report.CLEANUP_COLUMN == "Complexity Cleanup Notes"

    def test_unselected_rows_leave_the_column_empty(self, entries):
        wb = self._book(entries, {})
        ws = wb["Circuits"]
        col = [c.value for c in ws[1]].index(report.CLEANUP_COLUMN)
        assert all(row[col].value in (None, "") for row in ws.iter_rows(min_row=2))

    def test_a_selected_row_carries_its_note(self, entries, body_left):
        s = report.selection_for(body_left, report.KIND_CIRCUIT, "CKT_500")
        wb = self._book(entries, {s.key: s})
        ws = wb["Circuits"]
        headers = [c.value for c in ws[1]]
        col = headers.index(report.CLEANUP_COLUMN)
        ident = headers.index("Circuit")
        notes = {row[ident].value: row[col].value
                 for row in ws.iter_rows(min_row=2)}
        assert notes["CKT_500"] and "No build of" in notes["CKT_500"]
        assert not notes["CKT_100"], "an unticked row must stay empty"

    def test_cleanup_sheet_lists_only_the_selection(self, entries, body_left):
        picks = {}
        for kind, ident in ((report.KIND_CIRCUIT, "CKT_500"),
                            (report.KIND_GAP, "ZZZ")):
            s = report.selection_for(body_left, kind, ident)
            picks[s.key] = s
        ws = self._book(entries, picks)["Complexity Cleanup"]
        rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0]]
        assert len(rows) == 2
        assert {r[3] for r in rows} == {"CKT_500", "ZZZ"}

    def test_empty_selection_still_produces_a_valid_workbook(self, entries):
        ws = self._book(entries, {})["Complexity Cleanup"]
        assert ws.max_row == 1          # header only

    def test_read_me_states_the_programme(self, entries):
        ws = self._book(entries, {})["Read Me"]
        text = " ".join(str(r[0]) for r in ws.iter_rows(values_only=True) if r[0])
        assert "2030QX" in text and "V1_A" in text
        assert report.CLEANUP_COLUMN in text

    def test_family_and_harness_are_both_reported(self, entries):
        # a family mapped to several harnesses needs both to tell rows apart
        ws = self._book(entries, {})["Circuits"]
        headers = [c.value for c in ws[1]]
        assert headers[0] == "DTx family" and headers[1] == "Harness"
