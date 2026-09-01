"""The circuit chart: which part number carries which wire.

The chart is written in the Circuit Summary layout on purpose, so the strong
test is not "does it look right" but "does Circuit Health's own reader take it
back". Everything else here guards the marks themselves.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).parent))

from fixtures_dtxcircuits import circuit_rows, harnesses  # noqa: E402

from splice.dtxcircuits import analyze_harness, chart, report
from splice.dtxcircuits.models import CircuitRow, DtxMeta
from splice.inline.summary import SHEET, read_circuit_summary


META = DtxMeta(program="9000ZZ", phase="X9_A")


def _entries(rows, families=("BODY_LEFT", "IP")):
    books = harnesses()
    return [report.Entry(
        label=f"{fam} → {books[fam].name}", family=fam,
        filename=f"{fam}.xlsm",
        analysis=analyze_harness([r for r in rows if r.harness_family == fam],
                                 books[fam], harness_name=books[fam].name))
        for fam in families]


@pytest.fixture()
def charts():
    rows = circuit_rows()
    return chart.build_charts(_entries(rows), rows)


def _by_family(charts):
    return {c.family: c for c in charts}


class TestShape:
    def test_one_chart_per_pairing(self, charts):
        assert {c.family for c in charts} == {"BODY_LEFT", "IP"}

    def test_the_block_title_is_what_the_parser_keys_on(self, charts):
        assert _by_family(charts)["BODY_LEFT"].block_title == "BODY_LEFT - 90001"

    def test_part_numbers_come_from_the_complexity(self, charts):
        body = _by_family(charts)["BODY_LEFT"]
        assert body.part_numbers == ["90000001AA", "90000002AA",
                                     "90000003AA", "90000004AA"]

    def test_a_circuit_with_two_ends_is_two_rows(self, charts):
        """CKT_700 lands in two cavities; the chart is per end, not per wire."""
        body = _by_family(charts)["BODY_LEFT"]
        ends = [r for r in body.rows if r.circuit == "CKT_700"]
        assert len(ends) == 2
        assert {(r.cnum, r.cavity) for r in ends} == {("C2", "3"), ("C3", "4")}

    def test_rows_are_ordered_for_reading(self, charts):
        body = _by_family(charts)["BODY_LEFT"]
        assert body.rows == sorted(
            body.rows, key=lambda r: (r.circuit, r.cnum, chart._cavity_key(r.cavity)))

    def test_cavities_sort_numerically(self):
        assert chart._cavity_key("2") < chart._cavity_key("10")
        assert chart._cavity_key("10") < chart._cavity_key("A1")


class TestMarks:
    def test_an_unconditional_circuit_is_carried_by_every_build(self, charts):
        body = _by_family(charts)["BODY_LEFT"]
        row = next(r for r in body.rows if r.circuit == "CKT_100")
        assert row.marks(body.part_numbers) == ["X", "X", "X", "X"]

    def test_a_variant_is_marked_only_where_it_is_built(self, charts):
        body = _by_family(charts)["BODY_LEFT"]
        row = next(r for r in body.rows if r.circuit == "CKT_400")   # AAA&BBB
        assert row.marks(body.part_numbers) == ["", "", "X", ""]

    def test_a_never_built_circuit_is_an_empty_row_and_says_so(self, charts):
        body = _by_family(charts)["BODY_LEFT"]
        row = next(r for r in body.rows if r.circuit == "CKT_500")   # CCC
        assert row.marks(body.part_numbers) == ["", "", "", ""]
        assert row.is_finding, "an empty row must be flagged, not just empty"
        assert body.findings == 1

    def test_both_ends_of_one_circuit_carry_the_same_marks(self, charts):
        """Applicability is a property of the wire, not of the cavity."""
        body = _by_family(charts)["BODY_LEFT"]
        ends = [r for r in body.rows if r.circuit == "CKT_700"]
        assert ends[0].marks(body.part_numbers) == ends[1].marks(body.part_numbers)

    def test_coverage_counts_ends_per_part_number(self, charts):
        body = _by_family(charts)["BODY_LEFT"]
        for pn in body.part_numbers:
            expected = sum(1 for r in body.rows if pn in r.builds)
            assert body.coverage(pn) == expected

    def test_an_untracked_code_reads_as_carried(self, charts):
        """CKT_600 rests on ZZZ, which BODY_LEFT does not track.

        The resolver treats an unknown code as present, so the chart must show
        the circuit as carried — showing it absent would invent a decision the
        data does not support.
        """
        body = _by_family(charts)["BODY_LEFT"]
        row = next(r for r in body.rows if r.circuit == "CKT_600")
        assert row.marks(body.part_numbers) == ["X", "X", "X", "X"]


class TestRoundTrip:
    """What we write, Circuit Health reads."""

    def _reread(self, charts):
        data = chart.build_chart_workbook(charts, META.program, META.phase)
        return read_circuit_summary(data, "chart.xlsx")

    def test_harnesses_and_builds_survive(self, charts):
        harns, _ends = self._reread(charts)
        assert set(harns) == {"90001", "90002"}
        assert [b.part_number for b in harns["90001"].builds] == \
            _by_family(charts)["BODY_LEFT"].part_numbers

    def test_every_end_survives(self, charts):
        _harns, ends = self._reread(charts)
        assert len(ends) == sum(len(c.rows) for c in charts)

    def test_the_marks_survive(self, charts):
        _harns, ends = self._reread(charts)
        body = _by_family(charts)["BODY_LEFT"]
        for row in body.rows:
            end = next(e for e in ends
                       if e.circuit == row.circuit and e.connector == row.cnum
                       and e.cavity == row.cavity)
            assert set(end.builds) == set(row.builds), row.circuit

    def test_the_sales_code_survives(self, charts):
        _harns, ends = self._reread(charts)
        body = _by_family(charts)["BODY_LEFT"]
        row = next(r for r in body.rows if r.circuit == "CKT_400")
        end = next(e for e in ends if e.circuit == "CKT_400")
        assert end.sales_code == row.expression

    def test_a_never_built_circuit_round_trips_as_carried_by_nothing(self, charts):
        _harns, ends = self._reread(charts)
        end = next(e for e in ends if e.circuit == "CKT_500")
        assert end.builds == frozenset()


class TestWorkbook:
    def test_the_sheet_is_named_for_the_parser(self, charts):
        data = chart.build_chart_workbook(charts)
        assert SHEET in load_workbook(io.BytesIO(data)).sheetnames

    def test_wire_physicals_are_left_blank_rather_than_invented(self, charts):
        """Size, material and colour are not in the DTx. A guessed gauge would
        be read as fact, so those columns stay empty."""
        _harns, ends = TestRoundTrip()._reread(charts)
        assert all(not (e.size or e.material or e.color) for e in ends)

    def test_the_review_workbook_carries_the_chart(self, charts):
        rows = circuit_rows()
        data = report.build_report(_entries(rows), {}, charts=charts)
        wb = load_workbook(io.BytesIO(data))
        assert SHEET in wb.sheetnames
        assert "Circuits" in wb.sheetnames, "the review sheets must still be there"

    def test_the_review_workbook_is_unchanged_without_a_chart(self):
        rows = circuit_rows()
        data = report.build_report(_entries(rows), {})
        assert SHEET not in load_workbook(io.BytesIO(data)).sheetnames


class TestEdges:
    def test_a_family_with_no_rows_yields_an_empty_chart(self):
        rows = circuit_rows()
        entries = _entries(rows, families=("IP",))
        built = chart.build_charts(entries, [r for r in rows
                                             if r.harness_family == "BODY_LEFT"])
        assert built and built[0].rows == []

    def test_a_duplicate_dtx_row_is_written_once(self):
        """The DTx repeats a row per configuration; the chart is per end."""
        rows = circuit_rows()
        doubled = rows + [r for r in rows if r.circuit == "CKT_100"]
        built = chart.build_charts(_entries(doubled), doubled)
        body = _by_family(built)["BODY_LEFT"]
        assert sum(1 for r in body.rows if r.circuit == "CKT_100") == 1

    def test_a_row_with_no_circuit_is_skipped(self):
        rows = circuit_rows() + [CircuitRow(harness_family="IP", circuit="",
                                            sales_code="AAA", cnum="C9", pin="9")]
        built = chart.build_charts(_entries(rows), rows)
        assert all(r.circuit for c in built for r in c.rows)
