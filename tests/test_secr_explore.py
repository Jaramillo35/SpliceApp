"""The Browse tab's three queries: open a SECR, search every document, facet the scope."""

from __future__ import annotations

from pathlib import Path

import pytest

from secrdb.core.secr import api
from secrdb.core.secr.importer import import_secr_files
from tests.secr_fixtures import build_secr_workbook


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    db_path = tmp_path_factory.mktemp("explore") / "corpus.db"
    import_secr_files([
        ("ip.xlsx", build_secr_workbook(secr_number="D50319A", harness_family="IP")),
        ("body.xlsx", build_secr_workbook(secr_number="D49957A", harness_family="BODY_LEFT",
                                          model_year="2027")),
    ], db_path=db_path)
    return db_path


def _id(db_path: Path, number: str) -> int:
    return next(r["id"] for r in api.search_secrs(number, db_path=db_path)
                if r["secr_number"] == number)


def test_a_secr_opens_into_changes_by_type(corpus):
    p = api.preview_secr(_id(corpus, "D50319A"), db_path=corpus)
    assert p["header"]["secr_number"] == "D50319A"
    assert p["scope"] == {"model_year": "2028", "program": "RU", "phase": "X1",
                          "harness_families": ["IP"]}
    kinds = [g["object_type"] for g in p["groups"]]
    assert kinds[:2] == ["connector", "circuit"], "connector first, then circuit"
    connectors = {o["object_id"]: o for o in p["groups"][0]["objects"]}
    assert {"D2784J", "X350A", "SD401"} <= set(connectors)
    assert connectors["D2784J"]["actions"] == ["PN CHANGE"]      # an ADD + DELETE pair, merged
    assert connectors["D2784J"]["changes"][0]["new_value"] == "D4Z080-000-B"
    assert connectors["SD401"]["dtcrs"] == ["50319"]
    assert p["totals"]["changes"] == sum(g["change_count"] for g in p["groups"])
    assert p["totals"]["by_object_type"]["connector"] == p["groups"][0]["change_count"]


def test_a_circuit_change_names_the_connectors_it_lands_on(corpus):
    p = api.preview_secr(_id(corpus, "D50319A"), db_path=corpus)
    circuits = {o["object_id"]: o for o in p["groups"][1]["objects"]}
    a937 = circuits["A937F"]
    assert {"I350X", "D2784J"} <= set(a937["cnums"]) and a937["dtcrs"] == ["49919"]
    ends = {(e["role"], e["cnum"], e["cavity"]) for c in a937["changes"] for e in c["endpoints"]}
    assert ("from", "I350X", "4") in ends and ("to", "D2784J", "7") in ends
    # a comment naming two DTCRs puts the change under both
    assert circuits["C205"]["dtcrs"] == ["50315", "50317"]


def test_the_same_changes_roll_up_by_dtcr_and_by_cnum(corpus):
    p = api.preview_secr(_id(corpus, "D50319A"), db_path=corpus)
    dtcrs = {d["dtcr_number"]: d for d in p["dtcrs"]}
    assert "A937F" in dtcrs["49919"]["circuits"] and "X350A" in dtcrs["49919"]["connectors"]
    assert "D2784J" in dtcrs["49919"]["cnums"]
    assert {"49754", "50319"} <= set(dtcrs), "DTCRs named only in the header are listed too"
    assert dtcrs["49754"]["change_count"] == 0
    cnums = {c["cnum"]: c for c in p["cnums"]}
    assert cnums["D2784J"]["connector_changes"] == 1 and "A937F" in cnums["D2784J"]["circuits"]
    assert cnums["D2784J"]["dtcrs"] == ["49919"]
    assert api.preview_secr(999999, db_path=corpus) is None


def test_search_finds_text_anywhere_and_says_where(corpus):
    # a word that only exists inside a change value, in the middle of it
    rows = api.search_documents("4Z080", db_path=corpus)
    assert {r["secr_number"] for r in rows} == {"D50319A", "D49957A"}
    hit = rows[0]["hits"][0]
    assert hit["where"] == "change" and hit["object_id"] == "D2784J" and "4Z080" in hit["snippet"]
    assert hit["label"] == "connector D2784J · new value"
    # the stored workbook's file name
    rows = api.search_documents("body.xl", db_path=corpus)
    assert [r["secr_number"] for r in rows] == ["D49957A"]
    assert rows[0]["hits_by_place"].get("file") or rows[0]["hits_by_place"].get("header")
    # a header field
    rows = api.search_documents("aguilar", db_path=corpus)
    assert len(rows) == 2 and rows[0]["hits"][0]["label"] == "SECR author"
    assert api.search_documents("no-such-text-anywhere", db_path=corpus) == []


def test_search_is_capped_per_document_and_says_how_much_more(corpus):
    from secrdb.core.secr.explore import search_documents
    rows = search_documents("D", db_path=corpus, hits_per_document=3)
    assert all(len(r["hits"]) <= 3 for r in rows)
    assert any(r["more_hits"] > 0 and r["hit_count"] == 3 + r["more_hits"] for r in rows)


def test_no_text_lists_the_filtered_secrs(corpus):
    rows = api.search_documents("", db_path=corpus, model_year="2027")
    assert [r["secr_number"] for r in rows] == ["D49957A"] and rows[0]["hits"] == []
    assert rows[0]["harness_families"] == ["BODY_LEFT"] and rows[0]["change_count"] > 0
    with pytest.raises(ValueError, match="not a SECR filter"):
        api.search_documents("", db_path=corpus, colour="red")


def test_facets_count_the_scope_and_never_filter_themselves(corpus):
    f = api.scope_facets(db_path=corpus)
    assert f["totals"]["secrs"] == 2
    assert [(r["name"], r["secrs"]) for r in f["model_year"]] == [("2027", 1), ("2028", 1)]
    assert {r["name"] for r in f["harness_family"]} == {"IP", "BODY_LEFT"}
    picked = api.scope_facets(db_path=corpus, model_year="2027")
    assert picked["totals"]["secrs"] == 1
    assert [r["name"] for r in picked["model_year"]] == ["2027", "2028"], "siblings stay"
    assert [r["selected"] for r in picked["model_year"]] == [True, False]
    assert [r["name"] for r in picked["harness_family"]] == ["BODY_LEFT"]
    assert all(r["changes"] > 0 for r in f["program"])


def test_a_search_row_carries_the_list_columns_and_no_more(corpus):
    from secrdb.core.secr.explore import LIST_COLUMNS
    (row,) = api.search_documents("aguilar", db_path=corpus, model_year="2027")
    assert set(row) == set(LIST_COLUMNS) | {"hit_count", "hits_by_place", "hits",
                                           "more_hits", "harness_families"}
    assert row["hits"][0]["label"] == "SECR author", "hits still see the full header"
