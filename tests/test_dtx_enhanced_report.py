"""Enhanced DTx Compare workbook — sheets, Status column, dashboard, DTCR gate."""

from __future__ import annotations

import io

import pandas as pd
import pytest
from openpyxl import load_workbook

from splice.dtx_compare.enhanced_report import (
    DTCRRequiredError,
    build_yellow_connectors_df,
    generate_enhanced_dtx_report,
)


def test_yellow_connectors_from_invalid_connector_pn():
    new_rows = pd.DataFrame({
        "CNUM": ["D1", "D1", "D2", "D3"],
        "Connector PN": ["Invalid_Contact_Connector_Enginner | 5", "805-1", "Invalid_Contact_Connector_Enginner", "770-2"],
        "Device Name": ["Mod_A", "Mod_A", "Ant_B", "Sw_C"],
        "Harness Family": ["IP", "IP", "DASH", "IP"],
    })
    df = build_yellow_connectors_df(new_rows)
    assert list(df["CNUM"]) == ["D2", "D1"]        # one row per CNUM, sorted by family then CNUM
    assert "Connector PN" in df.columns and df.iloc[0]["Harness Family"] == "DASH"


@pytest.fixture(scope="module")
def showcase_files():
    """The invented showcase exports: OLD, NEW and a DTCR report (no customer data)."""
    import tempfile
    from pathlib import Path
    from demo import showcase
    with tempfile.TemporaryDirectory(prefix="showcase_dtx_") as td:
        out = Path(td)
        showcase.build(out)
        folder = out / "4_dtx_compare"
        old, new, dtcr = (next(folder.glob("*_OLD.xlsx")), next(folder.glob("*_NEW.xlsx")),
                          next(folder.glob("DTCR_Report_*.xlsx")))
        yield {"old": (old.read_bytes(), old.name), "new": (new.read_bytes(), new.name),
               "dtcr": (dtcr.read_bytes(), dtcr.name)}


def test_the_compare_runs_without_a_dtcr_report(showcase_files):
    """The DTCR report is optional: the change workbook is built without it,
    the DTCR# column stays (empty) so the dashboard's column letters hold, and
    nothing DTCR-shaped is written or returned."""
    f = showcase_files
    r = generate_enhanced_dtx_report(f["old"][0], f["new"][0], f["old"][1], f["new"][1])
    assert r["dtcr_matching_df"] is None and r["dtcr_matching_bytes"] is None
    wb = load_workbook(io.BytesIO(r["output_excel_bytes"]))
    assert "DTCR Matching" not in wb.sheetnames
    for sheet in ("Dashboard", "All Changes", "Yellow Connectors", "PreOrder List"):
        assert sheet in wb.sheetnames
    ac = wb["All Changes"]
    assert ac.cell(1, 1).value == "Status" and ac.cell(1, 2).value == "DTCR#"
    assert all(ac.cell(row, 2).value in (None, "") for row in range(2, ac.max_row + 1))
    db = wb["Dashboard"]
    assert len(db._charts) == 2, "no DTCR coverage pie without a DTCR report"
    texts = [str(c.value) for row in db.iter_rows() for c in row if c.value]
    assert any("No DTCR report was provided" in t for t in texts)
    assert r["added_circuit_count"] == 2                      # the planted QK106 / QK702
    assert DTCRRequiredError.__doc__ and "no longer" in DTCRRequiredError.__doc__


def test_with_a_dtcr_report_the_matching_comes_in_the_workbook_and_on_its_own(showcase_files):
    """Three files: the change workbook keeps its DTCR Matching sheet AND the
    same table is returned as a separate file the SECR Database can take."""
    from splice.dtx_compare.engine import load_dtcr_report
    from secrdb.core.dtcr.library import _COLUMNS, read_report
    f = showcase_files
    dtcr = load_dtcr_report(f["dtcr"][0], f["dtcr"][1])
    r = generate_enhanced_dtx_report(f["old"][0], f["new"][0], f["old"][1], f["new"][1], dtcr)
    wb = load_workbook(io.BytesIO(r["output_excel_bytes"]))
    assert "DTCR Matching" in wb.sheetnames
    assert r["output_file_name"].startswith("DTx_Change_Report_")
    # the standalone file is the SECR Database's input: same columns, first sheet
    frame = read_report(r["dtcr_matching_bytes"])
    assert set(_COLUMNS) <= set(frame.columns)
    assert len(frame) == len(r["dtcr_matching_df"]) > 0
    assert r["dtcr_matching_file_name"].startswith("DTCR_Matching_Report_") \
        and r["dtcr_matching_file_name"].endswith(".xlsx")
    assert r["dtcr_matching_file_name"] != r["output_file_name"]


def test_matching_only_is_the_same_file_under_the_download_names(showcase_files):
    from splice.dtx_compare.engine import generate_dtcr_matching_report, load_dtcr_report
    f = showcase_files
    dtcr = load_dtcr_report(f["dtcr"][0], f["dtcr"][1])
    r = generate_dtcr_matching_report(f["old"][0], f["new"][0], f["old"][1], f["new"][1], dtcr)
    assert r["output_excel_bytes"] == r["dtcr_matching_bytes"]
    assert r["output_file_name"] == r["dtcr_matching_file_name"]
    assert "Match Method" in r["dtcr_matching_df"].columns


def test_the_matching_file_name_states_the_scope_the_secr_library_reads():
    """The SECR Database files a DTCR Matching Report under program / model
    year / phase parsed from its name; the name must carry them the way the
    change report does (programme once, both phases, the later one wins)."""
    from unittest import mock
    from secrdb.core.dtcr.library import parse_scope_from_filename
    from splice.dtx_compare import engine, labels
    old = labels.ReportLabel(program="2028RU", phase="X1", source="title block")
    new = labels.ReportLabel(program="2028RU", phase="X2_A", source="title block")
    with mock.patch.object(labels, "resolve", side_effect=[old, new]):
        name = engine.dtcr_matching_file_name(b"o", b"n", "old.xls", "new.xls")
    assert name.startswith("DTCR_Matching_Report_2028RU_X1_vs_X2_A_")
    scope = parse_scope_from_filename(name)
    assert scope.is_complete and (scope.program, scope.model_year, scope.phase) == ("RU", "28", "X2")
    # files that state no programme fall back to their names, and the library asks
    with mock.patch.object(labels, "resolve", side_effect=[labels.ReportLabel(), labels.ReportLabel()]):
        name = engine.dtcr_matching_file_name(b"o", b"n", "left (1).xls", "right.xls")
    assert name.startswith("DTCR_Matching_Report_left_1_vs_right_")
    assert not parse_scope_from_filename(name).is_complete


@pytest.fixture(scope="module")
def _real(request):
    from pathlib import Path
    d = Path("/Users/martinjaramillo/Downloads/Development/data/Validatehere")
    files = {
        "old": d / "28RU_X1_DetailedDTxCircuitsReport_4_22_26 (31) 3.xls",
        "new": d / "DetailedDTxCircuitsReport (28_RU_X2) (2) 1.xls",
        "dtcr": d / "DTCRReport (1).xls",
    }
    if not all(p.exists() for p in files.values()):
        pytest.skip("real DTx/DTCR sample files absent")
    from splice.dtx_compare.engine import load_dtcr_report
    dtcr = load_dtcr_report(files["dtcr"].read_bytes(), files["dtcr"].name)
    return generate_enhanced_dtx_report(
        files["old"].read_bytes(), files["new"].read_bytes(), "28RU_X1.xls", "28RU_X2.xls", dtcr)


def test_enhanced_workbook_sheets_status_and_dashboard(_real):
    wb = load_workbook(io.BytesIO(_real["output_excel_bytes"]))
    # the WEAVE deliverables are all present as sheets
    for sheet in ("Dashboard", "All Changes", "DTCR Matching", "Yellow Connectors", "PreOrder List"):
        assert sheet in wb.sheetnames
    # requested sheet order: Dashboard, DTCR Matching, Yellow Connectors, All Changes, …
    order = wb.sheetnames
    assert order[0] == "Dashboard"
    assert order.index("DTCR Matching") < order.index("Yellow Connectors") < order.index("All Changes")

    ac = wb["All Changes"]
    assert ac.cell(1, 1).value == "Status" and ac.cell(1, 2).value == "DTCR#"   # Status before DTCR#
    assert len(ac.data_validations.dataValidation) == 1                          # the Status dropdown
    assert len(ac.conditional_formatting._cf_rules) >= 1                         # status row-coloring
    # DTCR# is a live array formula flowing from the DTCR Matching sheet by CNUM
    dtcr_cell = ac.cell(2, 2).value
    dtcr_formula = getattr(dtcr_cell, "text", dtcr_cell)          # openpyxl wraps array formulas
    assert "DTCR Matching" in str(dtcr_formula) and "TEXTJOIN" in str(dtcr_formula)

    db = wb["Dashboard"]
    assert db["A23"].value == "My Harnesses" and db["B23"].value == "Harness Family"   # picker column
    assert db["B9"].value.startswith("=SUMPRODUCT")                               # scoped Done count
    assert db["B14"].value.startswith("=IF")                                      # % complete
    assert db["A12"].value == "Not started"                                       # Not-started row present
    assert len(db._charts) == 3                                                   # progress donut, by-family bar, DTCR pie


def test_result_carries_every_key_the_page_hard_indexes(_real):
    """Field report 2026-08-23: the page crashed with KeyError 'old_layout' —
    the enhanced path dropped keys the classic engine used to return. Keep the
    page's full contract pinned so a missing key fails here, not in front of
    an engineer."""
    page_contract = {
        "added_cnum_count", "removed_cnum_count", "added_circuit_count",
        "removed_circuit_count", "modified_circuit_count",
        "old_layout", "new_layout",
        "added_circuits_df", "removed_circuits_df", "modified_circuits_df",
        "cnum_summary_df", "field_change_frequency_df",
        "output_excel_bytes", "output_file_name",
    }
    missing = page_contract - set(_real)
    assert not missing, f"enhanced result is missing page keys: {sorted(missing)}"
    assert _real["old_layout"].sheet_name and _real["new_layout"].sheet_name


def test_normalize_frame_matches_the_per_cell_form():
    """The vectorised normaliser must agree with ``normalize_cell`` on every
    kind of cell an export produces: None, NaN, padded strings, ints, floats,
    empty strings, and columns that are purely numeric."""
    import numpy as np
    import pandas as pd
    from splice.common.text import normalize_cell
    from splice.dtx_compare.engine import _normalize_frame

    frame = pd.DataFrame({
        "mixed": [None, np.nan, "  padded ", 5, 5.0, "", "x"],
        "ints": [1, 2, 3, 4, 5, 6, 7],
        "floats": [1.5, np.nan, 2.0, 3.25, 4.0, 5.5, 6.0],
        "strings": [" a", "b ", None, " c ", "", "d", np.nan],
    }, dtype=object)
    expected = frame.map(normalize_cell)
    got = _normalize_frame(frame)
    pd.testing.assert_frame_equal(got, expected, check_dtype=False)
