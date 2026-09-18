"""The SECR data explorer, driven as a user would — no browser.

Two invented SECRs (tests/secr_fixtures) in a database of their own. What is
pinned is what the explorer is for: the scope is stated and the facets
combine without hiding their siblings; a search says why each SECR matched;
a result opens into the same changes seen three ways; opening from a match
lands on the object that matched; and any DTCR or CNUM can become a search.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "secr.db"
    monkeypatch.setenv("SECRDB_DB_PATH", str(path))
    monkeypatch.setenv("SECRDB_DATA_DIR", str(tmp_path))
    from secrdb.core.secr import db as secr_db
    monkeypatch.setattr(secr_db, "DB_PATH", path)
    from secrdb.core.secr.importer import import_secr_files
    from tests.secr_fixtures import build_secr_workbook
    import_secr_files([
        ("ip.xlsx", build_secr_workbook(secr_number="D50319A", harness_family="IP")),
        ("body.xlsx", build_secr_workbook(secr_number="D49957A",
                                          harness_family="BODY_LEFT", model_year="2027")),
    ], db_path=path)
    return path


async def _fire(element) -> None:
    for listener in element._event_listeners.values():
        if listener.type == "click":
            out = listener.handler(None)
            if inspect.isawaitable(out):
                await out
    await asyncio.sleep(0.3)


async def press(user: User, text: str) -> None:
    """The button whose label is exactly ``text`` — never 'any element containing it'."""
    matches = [b for b in user.find(ui.button).elements if b.text == text]
    assert len(matches) == 1, f"{text!r}: found {len(matches)}"
    assert matches[0].enabled, f"{text!r} is disabled"
    await _fire(matches[0])


async def press_marked(user: User, marker: str) -> None:
    elements = list(user.find(marker=marker).elements)
    assert len(elements) == 1, f"marker {marker!r}: found {len(elements)}"
    await _fire(elements[0])


async def wait_for(user: User, text: str, seconds: float = 20.0) -> None:
    deadline = asyncio.get_event_loop().time() + seconds
    while True:
        try:
            await user.should_see(text, retries=1)
            return
        except AssertionError:
            if asyncio.get_event_loop().time() > deadline:
                raise
            await asyncio.sleep(0.2)


def field(user: User, label: str) -> ui.input:
    return next(e for e in user.find(ui.input).elements if e._props.get("label") == label)


def marked(user: User, prefix: str) -> set:
    return {m for e in user.find(ui.button).elements for m in e._markers if m.startswith(prefix)}


async def search(user: User, text: str) -> None:
    field(user, "Search").set_value(text)
    await press(user, "Search")


class TestScope:
    async def test_the_scope_is_stated_and_every_facet_is_counted(self, user: User, corpus):
        await user.open("/secr")
        await wait_for(user, "2 SECRs · 18 changes")
        for chip in ("2027 · 1", "2028 · 1", "BODY_LEFT · 1", "IP · 1"):
            await user.should_see(chip)
        # one value is a fact, not a choice: said in words, not offered as a chip
        await user.should_see("Every SECR here: Program RU · Phase X1 · Origin imported")
        assert not [b for b in user.find(ui.button).elements if b.text in ("RU · 2", "X1 · 2")]
        assert marked(user, "result-") == {"result-D50319A", "result-D49957A"}

    async def test_a_facet_narrows_the_list_but_keeps_its_siblings(self, user: User, corpus):
        await user.open("/secr")
        await wait_for(user, "2 SECRs · 18 changes")
        await press(user, "2028 · 1")
        await wait_for(user, "1 SECR · 9 changes in this scope")
        assert marked(user, "result-") == {"result-D50319A"}
        await user.should_see("2027 · 1")             # the other year is one click away
        await user.should_not_see("BODY_LEFT · 1")     # a family 2028 does not have
        await press(user, "Clear search and filters")
        await wait_for(user, "2 SECRs · 18 changes")


class TestSearch:
    async def test_a_match_says_where_it_was_found(self, user: User, corpus):
        await user.open("/secr")
        await wait_for(user, "2 SECRs · 18 changes")
        await search(user, "A937")
        await wait_for(user, "Matches · 2")
        await user.should_see("2 matches — 1 change · 1 affected item")
        assert "hit-D50319A-0" in marked(user, "hit-")

    async def test_nothing_found_says_so_in_words(self, user: User, corpus):
        await user.open("/secr")
        await wait_for(user, "2 SECRs · 18 changes")
        await search(user, "no-such-thing")
        await wait_for(user, "No SECR contains “no-such-thing” in this scope")

    def test_the_marked_snippet_is_escaped_before_it_is_marked(self):
        from nicegui_app.pages.secr_explore import marked as mark
        out = mark("<b>a937f</b> lands", "A937")
        assert "<b>" not in out and "&lt;b&gt;" in out
        assert out.count("<mark") == 1 and "a937" in out.lower()


class TestPreview:
    async def test_a_result_opens_into_its_changes_old_beside_new(self, user: User, corpus):
        await user.open("/secr")
        await wait_for(user, "2 SECRs · 18 changes")
        await press_marked(user, "result-D50319A")
        await wait_for(user, "Connector changes")
        for text in ("MY2028", "IP", "Circuit changes", "By action:"):
            await user.should_see(text)
        rows = [r for t in user.find(ui.table).elements for r in t.rows]
        pn = next(r for r in rows if r.get("object") == "SD401" and r.get("field") == "DEF_Connector_PN")
        assert (pn["old"], pn["new"], pn["dtcrs"]) == ("PN-OLD", "PN-NEW", "50319")
        labels = {col["label"] for t in user.find(ui.table).elements for col in t.columns}
        assert {"Object", "Old", "New"} <= labels and "old_value" not in labels

    async def test_opening_from_a_match_lands_on_the_object_that_matched(self, user: User, corpus):
        await user.open("/secr")
        await wait_for(user, "2 SECRs · 18 changes")
        await search(user, "A937")
        await wait_for(user, "Matches · 2")
        await press_marked(user, "hit-D50319A-0")
        await wait_for(user, "Find in this SECR")
        assert field(user, "Find in this SECR").value == "A937F"
        objects = {r["object"] for t in user.find(ui.table).elements for r in t.rows}
        assert objects == {"A937F"}

    async def test_a_dtcr_can_become_a_search_across_every_secr(self, user: User, corpus):
        await user.open("/secr")
        await wait_for(user, "2 SECRs · 18 changes")
        await press_marked(user, "result-D50319A")
        await wait_for(user, "Connector changes")
        await press(user, "By DTCR")
        await wait_for(user, "what each one changed, and why")
        await user.should_see("named in the header only")     # 49754 is only in the header
        await press(user, "50319")
        await wait_for(user, "Matches · ")
        assert field(user, "Search").value == "50319"

    async def test_the_cnum_lens_lists_what_lands_on_each_connector(self, user: User, corpus):
        await user.open("/secr")
        await wait_for(user, "2 SECRs · 18 changes")
        await press_marked(user, "result-D50319A")
        await wait_for(user, "Connector changes")
        await press(user, "By CNUM")
        await wait_for(user, "busiest first")
        await user.should_see("1 connector change · 1 circuit change")
