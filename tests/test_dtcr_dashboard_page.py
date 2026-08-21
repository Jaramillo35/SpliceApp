"""End-to-end test of the DTCR Reports tab, driven through Streamlit itself.

The library is only useful if the page actually renders it, so this drives the
real page: an empty library explains itself, a filed report is selectable, and
its numbers reach the screen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from secrdb.core.dtcr import library

from tests.test_dtcr_library import build_report

pytest.importorskip("streamlit.testing.v1")

from streamlit.testing.v1 import AppTest  # noqa: E402

PAGE = str(Path(__file__).resolve().parents[1] / "ui" / "pages" / "secr_database.py")


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "dash.db"
    monkeypatch.setenv("SECRDB_DB_PATH", str(path))
    monkeypatch.setenv("SECRDB_DATA_DIR", str(tmp_path))

    from secrdb.core.secr import db as secr_db

    monkeypatch.setattr(secr_db, "DB_PATH", path)
    return path


@pytest.fixture()
def app(db_path: Path) -> AppTest:
    return AppTest.from_file(PAGE, default_timeout=90)


def test_an_empty_library_says_so_instead_of_breaking(app: AppTest) -> None:
    at = app.run()

    assert not at.exception
    assert any(
        "No DTCR Matching Report has been filed" in info.value for info in at.info
    ), "the empty state did not render"


def test_a_filed_report_is_selectable_and_charted(
    app: AppTest, db_path: Path
) -> None:
    library.save_report(
        build_report(), "DTCR_Matching_Report_28RU_X1_vs_X2.xlsx",
        program="RU", model_year="28", phase="X2", db_path=db_path,
    )

    at = app.run()

    assert not at.exception
    picker = [box for box in at.selectbox if box.label == "Report"]
    assert picker, "the report selector did not render"
    assert "MY28 · RU · X2" in picker[0].value

    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["DTCRs"] == "5"
    assert metrics["No harness family"] == "1"
    assert at.dataframe, "the unassigned/rows tables did not render"


def test_two_scopes_can_be_switched_between(app: AppTest, db_path: Path) -> None:
    library.save_report(
        build_report(), "x2.xlsx", program="RU", model_year="28", phase="X2",
        db_path=db_path,
    )
    library.save_report(
        build_report([
            {"DTCR#": "1", "Status": "Complete", "Match Method": "Manual",
             "Harness Family": "IP"},
        ]),
        "x1.xlsx", program="RU", model_year="28", phase="X1", db_path=db_path,
    )

    at = app.run()
    picker = [box for box in at.selectbox if box.label == "Report"][0]
    assert len(picker.options) == 2

    other = next(o for o in picker.options if o != picker.value)
    at = picker.select(other).run()

    assert not at.exception
    assert {m.label: m.value for m in at.metric}["DTCRs"] in {"1", "5"}
