"""Programme and build phase for a DTx comparison.

The export's own title block is authoritative, but plenty of real exports have
been re-saved without one — those start straight at the header row. A label
must still come out, and it must say where it came from rather than implying
the file stated something it did not.
"""

from __future__ import annotations

import pytest

from splice.dtx_compare.engine import build_output_filename
from splice.dtx_compare.labels import (
    FROM_FILE_NAME,
    FROM_TITLE_BLOCK,
    UNKNOWN,
    ReportLabel,
    comparison_heading,
    comparison_slug,
    from_file_name,
    resolve,
)


class TestFromFileName:
    @pytest.mark.parametrize("name, program, phase", [
        ("DetailedDTxCircuitsReport (28_RU_X2) (2).xls", "2028RU", "X2"),
        ("2028WS_X2_A_DetailedDTxCircuitsReport_7-27-2026_1.xls", "2028WS", "X2_A"),
        ("28 RU X0 DetailedDTxCircuitsReport 20260120 1.xls", "2028RU", "X0"),
        ("2027KM_X2_A_DetailedDTxCircuitsReport_8.21.25.xls", "2027KM", "X2_A"),
        ("2028EJ_X1A_DTxCircuitsReport_05-21-26 1.xls", "2028EJ", "X1A"),
    ])
    def test_real_export_names_parse(self, name, program, phase):
        label = from_file_name(name)
        assert (label.program, label.phase) == (program, phase)
        assert label.source == FROM_FILE_NAME

    def test_a_following_word_is_not_read_as_the_phase_suffix(self):
        # "28 RU X1 DetailedDTx…" must be X1, not X1_D
        assert from_file_name("50795 - 28 RU X1 DetailedDTxCircuitsReport.xls").phase == "X1"

    def test_an_unrecognisable_name_yields_nothing_rather_than_a_guess(self):
        label = from_file_name("random.xls")
        assert not label.known and label.source == UNKNOWN


class TestResolve:
    def test_the_title_block_wins_when_present(self, tmp_path):
        import pandas as pd
        path = tmp_path / "export.xlsx"
        pd.DataFrame([["Detailed DTx Circuits Report"], ["Vehicle Program - 2028RU"],
                      ["Build Phase - X2_A"], [""], ["CNUM"]]).to_excel(
            path, index=False, header=False)
        # the name says something else entirely; the file's own words win
        label = resolve(path.read_bytes(), "2027KM_X0_whatever.xls")
        assert (label.program, label.phase) == ("2028RU", "X2_A")
        assert label.source == FROM_TITLE_BLOCK

    def test_a_file_without_a_title_block_falls_back_to_its_name(self, tmp_path):
        import pandas as pd
        path = tmp_path / "export.xlsx"
        pd.DataFrame([["CNUM", "Circuit Name"], ["C1", "K1"]]).to_excel(
            path, index=False, header=False)
        label = resolve(path.read_bytes(), "28 RU X1 DetailedDTxCircuitsReport.xls")
        assert (label.program, label.phase) == ("2028RU", "X1")
        assert label.source == FROM_FILE_NAME

    def test_unreadable_bytes_never_raise(self):
        assert resolve(b"not a workbook", "28_RU_X2.xls").phase == "X2"
        assert not resolve(b"not a workbook", "junk.xls").known


class TestDescribe:
    def test_it_states_where_the_label_came_from(self):
        label = ReportLabel("2028RU", "X2_A", FROM_TITLE_BLOCK, "export.xls")
        text = label.describe()
        assert "2028RU X2_A" in text and "title block" in text and "export.xls" in text

    def test_an_unknown_label_falls_back_to_the_file_name(self):
        assert ReportLabel(file_name="mystery.xls").describe() == "mystery.xls"

    def test_the_export_date_is_carried_next_to_the_phase(self):
        """Two exports of the same phase differ by nothing else, so the date
        has to travel with the label rather than sit in a separate field."""
        label = ReportLabel("2028RU", "X2_A", FROM_TITLE_BLOCK, "export.xls",
                            report_date="Jul-21-2026 07:53 AM")
        assert label.text_with_date == "2028RU X2_A · exported Jul-21-2026 07:53 AM"
        assert "Jul-21-2026" in label.describe()

    def test_a_label_with_no_date_reads_exactly_as_before(self):
        label = ReportLabel("2028RU", "X2_A", FROM_TITLE_BLOCK)
        assert label.text_with_date == "2028RU X2_A"


class TestSameDatePhases:
    """iSpeed labels successive exports of one phase identically.

    Seen in the field on 2028WS: both title blocks read X2_A and only the
    report date differed, so a report named "X2_A vs X2_A" identified nothing.
    """

    def _pair(self):
        return (ReportLabel("2028WS", "X2_A", FROM_TITLE_BLOCK,
                            report_date="Jul-15-2026 12:10 AM"),
                ReportLabel("2028WS", "X2_A", FROM_TITLE_BLOCK,
                            report_date="Jul-27-2026 04:51 PM"))

    def test_the_date_separates_them_in_the_file_name(self):
        old, new = self._pair()
        assert comparison_slug(old, new) == "2028WS_X2_A_20260715_vs_X2_A_20260727"

    def test_the_date_separates_them_in_the_heading(self):
        old, new = self._pair()
        assert comparison_heading(old, new) == \
            "2028WS X2_A (Jul-15-2026) → 2028WS X2_A (Jul-27-2026)"

    def test_distinct_phases_are_left_alone(self):
        old = ReportLabel("2028RU", "X1", FROM_TITLE_BLOCK,
                          report_date="Jan-01-2026 09:00 AM")
        new = ReportLabel("2028RU", "X2_A", FROM_TITLE_BLOCK,
                          report_date="Feb-01-2026 09:00 AM")
        assert comparison_slug(old, new) == "2028RU_X1_vs_X2_A"
        assert comparison_heading(old, new) == "2028RU X1 → 2028RU X2_A"

    def test_identical_phases_with_no_dates_do_not_gain_noise(self):
        old = ReportLabel("2028WS", "X2_A", FROM_TITLE_BLOCK)
        new = ReportLabel("2028WS", "X2_A", FROM_TITLE_BLOCK)
        assert comparison_slug(old, new) == "2028WS_X2_A_vs_X2_A"
        assert comparison_heading(old, new) == "2028WS X2_A → 2028WS X2_A"

    def test_the_date_slug_sorts(self):
        label = ReportLabel(report_date="Jul-05-2026 12:10 AM")
        assert label.date_slug == "20260705"
        assert label.short_date == "Jul-05-2026"
        assert ReportLabel(report_date="nonsense").date_slug == ""
        assert ReportLabel().date_slug == ""


class TestComparisonSlug:
    def test_a_shared_programme_is_stated_once(self):
        old = ReportLabel("2028RU", "X1", FROM_FILE_NAME)
        new = ReportLabel("2028RU", "X2_A", FROM_TITLE_BLOCK)
        assert comparison_slug(old, new) == "2028RU_X1_vs_X2_A"

    def test_different_programmes_are_both_named(self):
        old = ReportLabel("2027KM", "X2", FROM_FILE_NAME)
        new = ReportLabel("2028RU", "X1", FROM_FILE_NAME)
        assert comparison_slug(old, new) == "2027KM_X2_vs_2028RU_X1"

    def test_an_unknown_side_yields_no_slug(self):
        assert comparison_slug(ReportLabel(), ReportLabel("2028RU", "X2")) == ""


class TestOutputFilename:
    def test_the_phases_name_the_report(self):
        name = build_output_filename("old.xls", "new.xls", comparison="2028RU_X1_vs_X2_A")
        assert name.startswith("DTx_Change_Report_2028RU_X1_vs_X2_A_")
        assert name.endswith(".xlsx")

    def test_without_a_comparison_the_file_names_are_used_as_before(self):
        name = build_output_filename("old_report.xls", "new_report.xls")
        assert "old_report_vs_new_report" in name
