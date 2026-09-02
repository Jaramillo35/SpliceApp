"""Circuit Applicability, driven as a user would drive it — no browser.

These exist so the page can be restructured. Until now the only test of any
NiceGUI page was that its route registered; a 1,100-line page function could
be rearranged wrongly and nothing would notice. NiceGUI's simulated user
opens the page, feeds the showcase files through the real upload handlers,
clicks the real buttons, and reads what rendered.

The showcase programme is invented data (2030QX). Its numbers are pinned
here on purpose: seven families connect by name, one sales-code expression
is malformed, and after a run eight findings are pre-selected for review.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

SHOWCASE = Path(__file__).resolve().parents[1] / "demo" / "showcase" / "1_circuit_applicability"
DTX = SHOWCASE / "DetailedDTxCircuitsReport_30QX_V1_A.xlsx"
COMPLEXITIES = sorted(SHOWCASE.glob("2.- Harness_Complexity*.xlsx"))

pytestmark = pytest.mark.skipif(not DTX.exists(), reason="showcase files not built")


def StubFile(path: Path):
    """What ui.upload hands its handler. NiceGUI 3 insists on its own
    FileUpload type; SmallFileUpload is the in-memory one it uses itself."""
    from nicegui.elements.upload_files import SmallFileUpload
    return SmallFileUpload(
        path.name,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        path.read_bytes())


@pytest.fixture()
def store_path(tmp_path, monkeypatch) -> Path:
    """Every test gets its own workbench store, so nothing leaks between them."""
    from splice.dtxcircuits import store
    path = tmp_path / "workbench.json"
    monkeypatch.setattr(store, "STORE_PATH", path)
    return path


def in_order(elements):
    """``user.find(...).elements`` is a set. Two upload zones unpacked from a
    set land in either order — which put the DTx in the complexity zone on
    roughly half the runs and made every downstream assertion flaky.
    Creation order is the page order."""
    return sorted(elements, key=lambda e: e.id)


async def click_ancestor(user: User, text: str) -> None:
    """Click the nearest ancestor of ``text`` that listens for clicks.

    The master list's rows are plain divs with a click listener and a label
    inside; ``find(text).click()`` clicks the label, which listens for
    nothing. This walks up to the element that actually handles the click
    and calls its handler the way NiceGUI would.
    """
    import inspect
    element = in_order(user.find(text).elements)[0]
    while element is not None:
        listeners = [l for l in getattr(element, "_event_listeners", {}).values()
                     if l.type == "click"]
        if listeners:
            result = listeners[0].handler(None)
            if inspect.isawaitable(result):
                await result
            await _settle()
            return
        element = element.parent_slot.parent if element.parent_slot else None
    raise AssertionError(f"nothing above {text!r} handles a click")


async def _settle(seconds: float = 0.2) -> None:
    await asyncio.sleep(seconds)


async def wait_for(user: User, text: str, seconds: float = 30.0) -> None:
    """Poll until ``text`` is on the page, with a real timeout.

    ``should_see`` retries a fixed handful of times; loading nine workbooks
    or resolving seven harnesses takes longer than that on a busy machine,
    and a wait that is sometimes long enough is a flaky test.
    """
    deadline = asyncio.get_event_loop().time() + seconds
    while True:
        try:
            await user.should_see(text, retries=1)
            return
        except AssertionError:
            if asyncio.get_event_loop().time() > deadline:
                raise
            await asyncio.sleep(0.25)


async def open_loaded(user: User) -> None:
    """Open the page, feed the showcase files, and press Load and match."""
    await user.open("/circuit-applicability")
    await user.should_see("1 · Inputs")
    dtx_zone, complexity_zone = in_order(user.find(ui.upload).elements)
    await dtx_zone.handle_uploads([StubFile(DTX)])
    await complexity_zone.handle_uploads([StubFile(p) for p in COMPLEXITIES])
    # the upload handlers are async background tasks; the zones confirm
    # what they received, and that confirmation is what the click waits on
    await wait_for(user, f"✓ {DTX.name}")
    await wait_for(user, f"✓ {len(COMPLEXITIES)} files received")
    user.find("Load and match").click()
    await wait_for(user, "3 · Map families")


async def open_analysed(user: User) -> None:
    await open_loaded(user)
    user.find("Run analysis").click()
    await wait_for(user, "4 · Review")


class TestLoad:
    async def test_the_files_load_and_families_match_by_name(self, user: User, store_path):
        await open_loaded(user)
        await user.should_see("7 connected")
        await user.should_see("2 open")

    async def test_the_malformed_expression_is_caught_before_any_analysis(self, user: User, store_path):
        await open_loaded(user)
        await user.should_see("2 · Sales-code integrity")
        await user.should_see("1 unresolved")
        await user.should_see("QB1-QA1")

    async def test_nothing_downstream_shows_before_a_run(self, user: User, store_path):
        await open_loaded(user)
        await user.should_not_see("4 · Review")
        await user.should_not_see("5 · DTx data quality")
        await user.should_not_see("6 · Circuit chart")


class TestRun:
    async def test_every_downstream_card_appears_in_order(self, user: User, store_path):
        await open_analysed(user)
        await user.should_see("5 · DTx data quality")
        await user.should_see("6 · Circuit chart")
        await user.should_see("7 chart(s)")

    async def test_findings_are_preselected_for_the_customer(self, user: User, store_path):
        await open_analysed(user)
        await user.should_see("8 row(s) selected")
        saved = json.loads(store_path.read_text())
        assert len(saved["cleanup"]) == 8

    async def test_the_quality_card_counts_what_the_run_found(self, user: User, store_path):
        await open_analysed(user)
        await user.should_see("5 finding(s) for the customer")
        await user.should_see("2 family(ies) not assessed")

    async def test_the_master_list_names_the_harness_with_findings(self, user: User, store_path):
        await open_analysed(user)
        await user.should_see("IP · 9 ckt · 2 finding(s)")


class TestReview:
    async def test_unticking_a_row_is_remembered_as_a_dismissal(self, user: User, store_path):
        await open_analysed(user)
        await click_ancestor(user, "IP · 9 ckt")
        await user.should_see("QK107")
        ticked = [cb for cb in in_order(user.find(ui.checkbox).elements) if cb.value]
        assert ticked, "the never-built circuits arrive pre-ticked"
        ticked[0].set_value(False)
        await wait_for(user, "7 row(s) selected")
        saved = json.loads(store_path.read_text())
        assert saved["dismissed"], "an untick must survive to the next session"

    async def test_ticking_on_the_connectors_tab_keeps_you_on_it(self, user: User, store_path):
        """The bug this page once had: a tick refreshed the card and the tabs
        snapped back to Circuits, losing your place mid-review."""
        await open_analysed(user)
        await click_ancestor(user, "IP · 9 ckt")
        await user.should_see("Connectors (")
        tabs = in_order(user.find(ui.tabs).elements)[0]
        tabs.set_value("connectors")
        await wait_for(user, "connector(s) shown")
        boxes = in_order(user.find(ui.checkbox).elements)
        # the first box on the connectors panel; ticking it refreshes the card
        target = next(cb for cb in boxes if not cb.value)
        target.set_value(True)
        await _settle()
        await wait_for(user, "connector(s) shown")
        assert in_order(user.find(ui.tabs).elements)[0].value == "connectors"

    async def test_a_dismissed_row_is_not_reselected_by_the_next_run(self, user: User, store_path):
        await open_analysed(user)
        await click_ancestor(user, "IP · 9 ckt")
        await user.should_see("QK107")
        ticked = [cb for cb in in_order(user.find(ui.checkbox).elements) if cb.value]
        ticked[0].set_value(False)
        await wait_for(user, "7 row(s) selected")
        user.find("Run analysis").click()
        await _settle(1.0)
        await wait_for(user, "7 row(s) selected")
