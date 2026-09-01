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

from splice.dtxcircuits import analyze_harness, chart, conventions, report
from splice.dtxcircuits.models import CircuitRow, DtxMeta
from splice.inline.summary import SHEET, read_circuit_summary


META = DtxMeta(program="9000ZZ", phase="X9_A")


def _entries(rows, families=("BODY_LEFT", "IP"), with_complexity=True):
    books = harnesses()
    return [report.Entry(
        label=f"{fam} → {books[fam].name}", family=fam,
        filename=f"{fam}.xlsm",
        analysis=analyze_harness([r for r in rows if r.harness_family == fam],
                                 books[fam], harness_name=books[fam].name),
        complexity=books[fam] if with_complexity else None)
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

    def test_the_sales_code_survives_as_the_harness_form(self, charts):
        """The Sales Code column carries the condition restated in THIS
        harness's codes — that is the one true of this block's part numbers.
        The DTx wording rides along in Suffix so nothing is lost."""
        _harns, ends = self._reread(charts)
        body = _by_family(charts)["BODY_LEFT"]
        row = next(r for r in body.rows if r.circuit == "CKT_400")
        end = next(e for e in ends if e.circuit == "CKT_400")
        assert end.sales_code == (row.harness_expression or row.expression)
        if row.harness_expression and row.harness_expression != row.expression:
            assert end.suffix == row.expression

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


class TestUniversalCode:
    """``501`` alone means every harness part number (SE ruling, 2026-09-01)."""

    def test_a_bare_universal_code_is_unconditional(self):
        assert conventions.is_universal("501")
        assert conventions.effective_condition("501") is None
        assert conventions.effective_condition("  501 ") is None

    def test_inside_a_larger_expression_it_stays_an_ordinary_code(self):
        """The narrow reading the SE asked for: 501/RHV and 501&HAH are not
        rewritten, because widening the rule would silently restate them."""
        assert not conventions.is_universal("501/RHV")
        assert conventions.effective_condition("501/RHV") == "501/RHV"
        assert conventions.effective_condition("501&HAH") == "501&HAH"

    def test_a_bare_universal_circuit_is_carried_by_every_build(self):
        rows = circuit_rows() + [
            CircuitRow(harness_family="IP", circuit="CKT_970", sales_code="501",
                       cnum="C6", pin="6", connector_pn="99999999")]
        built = chart.build_charts(_entries(rows), rows)
        ip = _by_family(built)["IP"]
        row = next(r for r in ip.rows if r.circuit == "CKT_970")
        assert row.marks(ip.part_numbers) == ["X", "X"]
        assert row.expression == "", "a universal code is not a condition"

    def test_it_is_not_reported_as_a_sales_code_gap(self):
        """No complexity file lists 501, so reporting it gives the customer
        nothing they can act on."""
        from splice.dtxcircuits.analyze import code_gaps
        rows = [CircuitRow(harness_family="IP", circuit="CKT_970",
                           sales_code="501", cnum="C6", pin="6")]
        assert code_gaps(rows, harnesses()["IP"]) == []

    def test_but_a_mixed_expression_still_reports_its_real_gaps(self):
        from splice.dtxcircuits.analyze import code_gaps
        rows = [CircuitRow(harness_family="IP", circuit="CKT_971",
                           sales_code="501/ZZZ", cnum="C6", pin="6")]
        codes = {g.code for g in code_gaps(rows, harnesses()["IP"])}
        assert "ZZZ" in codes, "an untracked code in a mixed expression is real"


class TestFlow:
    """A circuit is one wire; its condition does not change at a boundary."""

    def _rows(self):
        return [
            CircuitRow(harness_family="IP", circuit="CKT_SPAN",
                       sales_code="AAA", cnum="C1", pin="1"),
            CircuitRow(harness_family="BODY_LEFT", circuit="CKT_SPAN",
                       sales_code="", cnum="C2", pin="2"),
            CircuitRow(harness_family="BODY_LEFT", circuit="CKT_TIGHT",
                       sales_code="AAA", cnum="C3", pin="3"),
            CircuitRow(harness_family="IP", circuit="CKT_TIGHT",
                       sales_code="BBB", cnum="C4", pin="4"),
        ]

    def test_a_condition_stated_in_one_harness_reaches_the_others(self):
        flowed = chart.flowed_conditions(self._rows())
        assert flowed["CKT_TIGHT"] == "(AAA)/(BBB)"

    def test_one_unconditional_end_makes_the_whole_circuit_unconditional(self):
        flowed = chart.flowed_conditions(self._rows())
        assert flowed["CKT_SPAN"] is None

    def test_a_bare_universal_end_counts_as_unconditional(self):
        rows = self._rows() + [CircuitRow(harness_family="DASH",
                                          circuit="CKT_TIGHT",
                                          sales_code="501", cnum="C5", pin="5")]
        assert chart.flowed_conditions(rows)["CKT_TIGHT"] is None

    def test_every_end_of_a_circuit_carries_the_flowed_condition(self):
        rows = self._rows()
        built = chart.build_charts(_entries(rows), rows)
        for c in built:
            for row in c.rows:
                if row.circuit == "CKT_TIGHT":
                    assert row.expression == "(AAA)/(BBB)"


class TestHarnessExpression:
    """Restated only where the harness has no column for a code."""

    def test_a_condition_already_in_the_vocabulary_is_left_alone(self, charts):
        body = _by_family(charts)["BODY_LEFT"]
        row = next(r for r in body.rows if r.circuit == "CKT_400")   # AAA&BBB
        assert row.harness_expression == row.expression

    def test_a_condition_on_an_untracked_code_is_restated(self):
        """BODY_LEFT does not track ZZZ, so (ZZZ) cannot be stated in its
        codes; it selects every build, which is not a condition at all."""
        rows = circuit_rows()
        body = _by_family(chart.build_charts(_entries(rows), rows))["BODY_LEFT"]
        row = next(r for r in body.rows if r.circuit == "CKT_600")
        assert row.harness_expression == ""
        assert row.marks(body.part_numbers) == ["X", "X", "X", "X"]

    def test_a_restatement_selects_exactly_the_same_builds(self):
        """Whatever wording comes back must not move a single mark."""
        from splice.inline.complexity import applies_in
        rows = circuit_rows()
        books = harnesses()
        for c in chart.build_charts(_entries(rows), rows):
            complexity = books[c.family]
            for row in c.rows:
                if not row.harness_expression:
                    continue
                selected = {b.part_number for b in complexity.builds
                            if applies_in(row.harness_expression, b.codes,
                                          complexity.complexity_codes)}
                assert selected == set(row.builds), row.circuit

    def test_all_builds_and_no_builds_are_not_conditions(self, charts):
        for c in charts:
            for row in c.rows:
                if not row.builds or len(row.builds) == len(c.part_numbers):
                    assert row.harness_expression == ""

    def test_without_a_complexity_file_it_falls_back_honestly(self):
        """No complexity means no restatement — and the marks come from the
        analysis, not from an empty set that would read as never built."""
        rows = circuit_rows()
        built = chart.build_charts(_entries(rows, with_complexity=False), rows)
        body = _by_family(built)["BODY_LEFT"]
        row = next(r for r in body.rows if r.circuit == "CKT_100")
        assert row.harness_expression == ""
        assert row.marks(body.part_numbers) == ["X", "X", "X", "X"]


class TestSplices:
    """Three ends is a branch, and a branch has to join somewhere."""

    def _rows(self, ends: int, family: str = "IP"):
        return [CircuitRow(harness_family=family, circuit="CKT_BRANCH",
                           sales_code="", cnum=f"C{i}", pin=str(i + 1))
                for i in range(ends)]

    def _chart(self, ends: int):
        rows = self._rows(ends)
        return _by_family(chart.build_charts(_entries(rows, families=("IP",)),
                                             rows))["IP"]

    def test_two_ends_is_a_wire_not_a_splice(self):
        c = self._chart(2)
        assert c.splices == {}
        assert not any(r.is_splice for r in c.rows)

    def test_three_ends_gets_a_splice(self):
        c = self._chart(3)
        assert c.splices == {"CKT_BRANCH": "SCKT_BRANCHA"}

    def test_the_splice_is_named_the_way_splice_generation_names_them(self):
        assert self._chart(3).splices["CKT_BRANCH"] == "SCKT_BRANCHA"

    def test_one_splice_cavity_per_branch(self):
        c = self._chart(4)
        cavities = [r.cavity for r in c.rows if r.is_splice]
        assert cavities == ["A", "B", "C", "D"]

    def test_the_splice_wires_carry_what_their_branch_carries(self):
        rows = self._rows(3)
        rows[0] = CircuitRow(harness_family="IP", circuit="CKT_BRANCH",
                             sales_code="AAA", cnum="C0", pin="1")
        c = _by_family(chart.build_charts(_entries(rows, families=("IP",)),
                                          rows))["IP"]
        device_ends = [r for r in c.rows if not r.is_splice]
        splice_ends = [r for r in c.rows if r.is_splice]
        assert len(splice_ends) == len(device_ends)
        assert {tuple(r.builds) for r in splice_ends} == \
               {tuple(r.builds) for r in device_ends}

    def test_cavities_continue_past_Z_rather_than_truncating(self):
        """A real ground net in 2028RU X2_A has 269 ends. Stopping at Z would
        silently drop wires."""
        c = self._chart(30)
        cavities = [r.cavity for r in c.rows if r.is_splice]
        assert cavities[:2] == ["A", "B"]
        assert cavities[25:28] == ["Z", "AA", "AB"]
        assert len(cavities) == 30

    def test_cavities_sort_in_allocation_order(self):
        assert chart._cavity_key("Z") < chart._cavity_key("AA")
        assert chart._cavity_key("AA") < chart._cavity_key("AB")
        assert chart._cavity_key("2") < chart._cavity_key("10")

    def test_splices_can_be_turned_off(self):
        rows = self._rows(5)
        c = _by_family(chart.build_charts(_entries(rows, families=("IP",)), rows,
                                          splice_min_ends=0))["IP"]
        assert c.splices == {}

    def test_a_spliced_chart_still_round_trips(self):
        rows = self._rows(4)
        built = chart.build_charts(_entries(rows, families=("IP",)), rows)
        data = chart.build_chart_workbook(built)
        _harns, ends = read_circuit_summary(data, "spliced.xlsx")
        assert len(ends) == 8, "four device ends and four splice ends"
        assert sum(1 for e in ends if e.connector == "SCKT_BRANCHA") == 4


class TestScale:
    """A real programme is ~5,400 circuit ends against ~20 part numbers.

    The first version styled each row via ``ws[ws.max_row]``. ``max_row``
    rescans every cell written so far, so the write was quadratic: 33 seconds
    for one export, run on the event loop, which dropped the browser's
    connection and read to the user as the app restarting. These tests hold
    the shape of the fix rather than a stopwatch — a timing assertion would
    be flaky on a loaded machine, but a quadratic write cannot pass a ratio
    check.
    """

    def _charts(self, families: int, ends: int, parts: int = 12):
        built = []
        for f in range(families):
            pns = [f"9900{f:02d}{k:02d}AA" for k in range(parts)]
            rows = [chart.ChartRow(
                circuit=f"QK{i:05d}", cnum=f"C{i % 40:03d}",
                cavity=str(i % 20 + 1), expression="(QA1/QB2)",
                classification="variant",
                builds=pns[: (i % parts) + 1]) for i in range(ends)]
            built.append(chart.Chart(family=f"FAM_{f}", harness=f"FAM_{f}",
                                     def_id=str(70000 + f),
                                     part_numbers=pns, rows=rows))
        return built

    def test_the_sheet_is_never_rescanned_while_writing(self):
        """The defect itself, pinned.

        ``max_row``/``max_column`` walk every cell written so far. Consulting
        either one per row is what made the export quadratic, so the writer
        tracks its own row index and must not read them back at all. A timing
        assertion would be flaky on a loaded machine; this cannot be.
        """
        from openpyxl.worksheet.worksheet import Worksheet

        reads = []
        for name in ("max_row", "max_column"):
            original = getattr(Worksheet, name)

            def probe(self, _name=name, _original=original):
                reads.append(_name)
                return _original.fget(self)

            monkey = property(probe)
            setattr(Worksheet, name, monkey)
        try:
            chart.build_chart_workbook(self._charts(3, 50))
        finally:
            # restore the real descriptors
            import importlib
            importlib.reload(importlib.import_module(
                "openpyxl.worksheet.worksheet"))

        assert not reads, (
            f"the writer rescanned the sheet {len(reads)} time(s): "
            f"{sorted(set(reads))}")

    def test_a_large_chart_still_round_trips(self):
        charts = self._charts(6, 400)
        data = chart.build_chart_workbook(charts, "9000ZZ", "X9_A")
        harns, ends = read_circuit_summary(data, "big.xlsx")
        assert len(harns) == 6
        assert len(ends) == sum(len(c.rows) for c in charts)


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
