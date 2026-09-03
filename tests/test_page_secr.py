"""SECR Database and Ask the Database, driven as a user would — no browser.

Records are searched: the Browse tab opens on the search row, every tab is
reachable by URL, the Import gate names what it needs, and the Ask page
renders its card whether or not the assistant is enabled.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch) -> Path:
    """An empty database of its own, so nothing on the machine leaks in."""
    path = tmp_path / "secr.db"
    monkeypatch.setenv("SECRDB_DB_PATH", str(path))
    monkeypatch.setenv("SECRDB_DATA_DIR", str(tmp_path))
    from secrdb.core.secr import db as secr_db
    monkeypatch.setattr(secr_db, "DB_PATH", path)
    return path


class TestSecrDatabase:
    async def test_the_browse_tab_opens_on_the_search_row(self, user: User, db_path):
        await user.open("/secr")
        await user.should_see("Search")
        # the shell and the Create form have inputs of their own — pick the
        # one labelled Search and check it is the clearable search row
        boxes = [e for e in user.find(ui.input).elements
                 if e._props.get("label") == "Search"]
        assert len(boxes) == 1
        assert "clearable" in boxes[0]._props

    async def test_results_carry_engineer_words_not_column_names(self, user: User, db_path):
        from secrdb.core.secr.importer import import_secr_files
        from tests.secr_fixtures import build_secr_workbook
        import_secr_files([("ip.xlsx", build_secr_workbook(secr_number="D50319A",
                                                          harness_family="IP"))],
                          db_path=db_path)
        await user.open("/secr")
        await user.should_see("Browse")
        # the simulated user reads labels, not table cells — inspect the table
        table = min(user.find(ui.table).elements, key=lambda e: e.id)
        assert [r["secr_number"] for r in table.rows] == ["D50319A"]
        labels = [col["label"] for col in table.columns]
        assert labels[:2] == ["SECR #", "Version"]
        assert "Matched on" in labels and "match_reason" not in labels

    async def test_the_library_tab_is_deep_linkable(self, user: User, db_path):
        await user.open("/secr?tab=library")
        await user.should_see("DTCR report library")
        tabs = next(iter(user.find(ui.tab_panels).elements))
        assert tabs.value == "library"

    async def test_an_unknown_tab_falls_back_to_browse(self, user: User, db_path):
        await user.open("/secr?tab=nonsense")
        tabs = next(iter(user.find(ui.tab_panels).elements))
        assert tabs.value == "browse"

    async def test_the_import_gate_names_what_it_needs(self, user: User, db_path):
        await user.open("/secr?tab=import")
        await user.should_see("Needs: at least one SECR workbook")
        button = next(b for b in user.find(ui.button).elements if b.text == "Import")
        assert not button.enabled

    async def test_the_create_gate_names_what_it_needs(self, user: User, db_path):
        await user.open("/secr?tab=create")
        await user.should_see("Needs: at least one DEF-to-DEF compare")


class TestAsk:
    async def test_the_page_renders_its_card(self, user: User, db_path):
        from secrdb.config import ASSISTANT_ENABLED
        await user.open("/ask")
        await user.should_see("Ask the Database")
        if ASSISTANT_ENABLED:
            await user.should_see("Clear thread")
            await user.should_see("Ask about SECRs, circuits, connectors or harnesses")
        else:
            await user.should_see("disabled by configuration")
