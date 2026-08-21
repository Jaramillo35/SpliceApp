"""End-to-end test of the Browse page, driven through Streamlit itself.

This exists because of a real field report: "I imported SECR files and then
clicked on browse, nothing is showing." The cause was the page error guard
swallowing the ``RerunException`` that ``st.rerun()`` raises — which cancelled
the rerun *and* halted the render, leaving a blank tab.

A unit test on the guard covers the mechanism. This covers the symptom: the
page renders, and interacting with it still renders.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from secrdb.core.secr.importer import import_secr_files

from tests.secr_fixtures import build_secr_workbook

pytest.importorskip("streamlit.testing.v1")

from streamlit.testing.v1 import AppTest  # noqa: E402

PAGE = str(Path(__file__).resolve().parents[1] / "ui" / "pages" / "secr_database.py")


@pytest.fixture()
def app(tmp_path: Path, monkeypatch) -> AppTest:
    """The Browse page over a small database of its own."""
    db_path = tmp_path / "browse.db"
    import_secr_files(
        [
            ("ip.xlsx", build_secr_workbook(secr_number="D50319A", harness_family="IP")),
            (
                "body.xlsx",
                build_secr_workbook(
                    secr_number="D49957A", harness_family="BODY_LEFT"
                ),
            ),
        ],
        db_path=db_path,
    )
    monkeypatch.setenv("SECRDB_DB_PATH", str(db_path))
    monkeypatch.setenv("SECRDB_DATA_DIR", str(tmp_path))

    from secrdb.core.secr import db as secr_db

    monkeypatch.setattr(secr_db, "DB_PATH", db_path)
    return AppTest.from_file(PAGE, default_timeout=60)


def test_the_page_renders_with_data(app: AppTest) -> None:
    at = app.run()

    assert not at.exception
    labels = [metric.label for metric in at.metric]
    assert "SECRs" in labels
    assert at.dataframe, "the SECR table did not render"


def test_searching_reruns_and_filters(app: AppTest) -> None:
    """The exact interaction that came back blank in the field."""
    at = app.run()
    before = at.metric[0].value

    at = at.text_input[0].set_value("D50319A").run()

    assert not at.exception, f"search raised: {at.exception}"
    assert at.metric[0].value != before, "the filter did not narrow the results"
    assert any("Search: D50319A" in button.label for button in at.button), (
        "the active-filter chip did not appear"
    )
    assert at.dataframe, "the table disappeared after searching"


def test_clearing_the_search_restores_everything(app: AppTest) -> None:
    at = app.run()
    everything = at.metric[0].value

    at = at.text_input[0].set_value("D50319A").run()
    narrowed = at.metric[0].value
    at = at.text_input[0].set_value("").run()

    assert not at.exception
    assert narrowed != everything
    assert at.metric[0].value == everything


def test_a_search_matching_nothing_says_so_rather_than_blanking(
    app: AppTest,
) -> None:
    at = app.run()

    at = at.text_input[0].set_value("NOTHING-MATCHES-THIS").run()

    assert not at.exception
    assert any("No SECRs match" in info.value for info in at.info)
