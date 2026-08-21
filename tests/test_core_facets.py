"""Tests for the change-explorer aggregates behind the charts.

The charts, the counters and the change table all read the same filters, so
these tests pin the two properties that make graph-as-filter behave: totals
honour every filter, and a facet never filters itself (otherwise selecting a
value collapses its own chart to one bar and you cannot switch to a sibling).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from secrdb.core.secr import db as secr_db
from secrdb.core.secr.importer import import_secr_files
from tests.secr_fixtures import build_secr_workbook


@pytest.fixture()
def populated(tmp_path: Path) -> Path:
    db_path = tmp_path / "facets.db"
    import_secr_files(
        [
            ("ip.xlsx", build_secr_workbook(secr_number="D1", harness_family="IP")),
            (
                "body.xlsx",
                build_secr_workbook(
                    secr_number="D2", harness_family="BODY", model_year="2027"
                ),
            ),
        ],
        db_path=db_path,
    )
    return db_path


def _names(rows) -> list:
    return [row["name"] for row in rows]


def test_totals_count_the_whole_database(populated: Path) -> None:
    facets = secr_db.change_facets(db_path=populated)
    totals = facets["totals"]

    assert totals["changes"] > 0
    assert totals["secrs"] == 2
    assert totals["connectors"] > 0
    assert totals["circuits"] > 0


def test_every_chart_has_data(populated: Path) -> None:
    facets = secr_db.change_facets(db_path=populated)
    for name in (
        "action", "object_type", "harness_family", "connectors", "circuits"
    ):
        assert facets[name], name
        assert all({"name", "n"} <= set(row) for row in facets[name])


def test_facet_rows_are_ordered_by_count(populated: Path) -> None:
    rows = secr_db.change_facets(db_path=populated)["action"]
    counts = [row["n"] for row in rows]
    assert counts == sorted(counts, reverse=True)


def test_a_filter_narrows_the_totals(populated: Path) -> None:
    everything = secr_db.change_facets(db_path=populated)["totals"]
    filtered = secr_db.change_facets(harness_family="IP", db_path=populated)["totals"]

    assert filtered["changes"] < everything["changes"]
    assert filtered["secrs"] == 1


def test_a_facet_does_not_filter_itself(populated: Path) -> None:
    """Selecting one harness must leave the other harnesses on its own chart."""
    unfiltered = _names(secr_db.change_facets(db_path=populated)["harness_family"])
    filtered = secr_db.change_facets(harness_family="IP", db_path=populated)

    assert set(_names(filtered["harness_family"])) == set(unfiltered)
    assert "BODY" in _names(filtered["harness_family"])
    # ...while every other chart *is* narrowed by it.
    assert filtered["totals"]["secrs"] == 1


def test_other_facets_are_narrowed_by_the_filter(populated: Path) -> None:
    everything = secr_db.change_facets(db_path=populated)
    filtered = secr_db.change_facets(action="PN CHANGE", db_path=populated)

    assert set(_names(filtered["action"])) == set(_names(everything["action"]))
    assert filtered["object_type"] != everything["object_type"]
    assert _names(filtered["object_type"]) == ["connector"]


def test_the_connector_chart_ignores_only_its_own_selection(
    populated: Path,
) -> None:
    """Clicking one CNUM must not reduce the CNUM chart to that CNUM."""
    unfiltered = _names(secr_db.change_facets(db_path=populated)["connectors"])
    filtered = secr_db.change_facets(cnum="D2784J", db_path=populated)

    assert set(_names(filtered["connectors"])) == set(unfiltered)
    assert filtered["totals"]["changes"] < secr_db.change_facets(
        db_path=populated
    )["totals"]["changes"]


def test_selecting_a_cnum_empties_the_circuit_chart(populated: Path) -> None:
    """CNUM and circuit are separate filter keys, so the circuit chart is
    narrowed by a CNUM selection instead of ignoring it — otherwise the KPI
    would read 'Circuits 0' beside a circuit chart full of bars."""
    facets = secr_db.change_facets(cnum="D2784J", db_path=populated)

    assert facets["totals"]["circuits"] == 0
    assert facets["circuits"] == []
    assert facets["totals"]["connectors"] == 1


def test_selecting_a_circuit_empties_the_connector_chart(populated: Path) -> None:
    facets = secr_db.change_facets(circuit="A937F", db_path=populated)

    assert facets["totals"]["connectors"] == 0
    assert facets["connectors"] == []
    assert facets["circuits"]  # its own chart keeps its siblings


def test_the_kpi_counts_match_their_charts(populated: Path) -> None:
    """Every headline number must agree with the chart beside it."""
    for filters in ({}, {"action": "CHG"}, {"harness_family": "IP"}):
        facets = secr_db.change_facets(top_n=1000, db_path=populated, **filters)
        rows = secr_db.find_changes(limit=10_000, db_path=populated, **filters)
        assert facets["totals"]["changes"] == len(rows), filters
        assert facets["totals"]["connectors"] == len(
            {r["object_id"] for r in rows if r["object_type"] == "connector"}
        ), filters
        assert facets["totals"]["circuits"] == len(
            {r["object_id"] for r in rows if r["object_type"] == "circuit"}
        ), filters


def test_filters_combine(populated: Path) -> None:
    facets = secr_db.change_facets(
        harness_family="IP", action="PN CHANGE", db_path=populated
    )
    assert facets["totals"]["secrs"] == 1
    assert _names(facets["object_type"]) == ["connector"]


def test_search_narrows_to_the_matching_changes(populated: Path) -> None:
    facets = secr_db.change_facets(query="D2784J", db_path=populated)
    rows = secr_db.find_changes(query="D2784J", db_path=populated)

    assert facets["totals"]["changes"] == len(rows)
    # A free-text hit is either the object itself or a circuit that terminates
    # on it — since v4 the endpoint columns are searched too.
    assert all(
        "D2784J" in str(row["object_id"])
        or "D2784J" in (str(row["from_dnum"]), str(row["to_dnum"]))
        for row in rows
    )


def test_facets_and_the_table_agree(populated: Path) -> None:
    """The number on a bar must equal the rows the same filter returns."""
    for action in _names(secr_db.change_facets(db_path=populated)["action"]):
        facets = secr_db.change_facets(action=action, db_path=populated)
        rows = secr_db.find_changes(action=action, limit=10_000, db_path=populated)
        assert facets["totals"]["changes"] == len(rows), action


def test_top_n_caps_each_chart(populated: Path) -> None:
    facets = secr_db.change_facets(top_n=2, db_path=populated)
    assert len(facets["circuits"]) <= 2
    assert len(facets["action"]) <= 2


def test_an_empty_database_returns_zeroed_facets(tmp_path: Path) -> None:
    facets = secr_db.change_facets(db_path=tmp_path / "empty.db")
    assert facets["totals"]["changes"] == 0
    assert facets["action"] == []
