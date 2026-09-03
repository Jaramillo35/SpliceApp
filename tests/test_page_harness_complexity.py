"""Harness Complexity, driven as a user would drive it — no browser.

The page was restructured into the workbench archetype (step bar, KPI
strip, gated primaries, downloads as buttons). NiceGUI's simulated user
opens it, feeds the showcase workbooks through the real upload handlers,
clicks the real buttons and reads what rendered — so the shape can be
changed again without anyone finding out in a demo.

The showcase programme is invented data (2030QX). demo/README.md pins what
the IP sheet carries: a C/O carryover, a DELETE row that is excluded, the
combined expression ``QB1+(QA1/QA2)`` awaiting a decision, and the equality
``QA1=QA2`` that auto-resolves.
"""

from __future__ import annotations

import asyncio
import inspect
import tempfile
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from demo import showcase


@pytest.fixture(scope="module")
def files() -> dict:
    """The showcase programme, built fresh — only its builder is committed."""
    with tempfile.TemporaryDirectory(prefix="showcase_") as td:
        out = Path(td)
        showcase.build(out)
        folder = out / "3_harness_complexity"
        yield {
            "crossref": folder / "Harness_Family_CrossRef.xlsx",
            "new": folder / "Master_Complexity_30QX_V1_A_NEW.xlsx",
            "old": folder / "Master_Complexity_30QX_V1_A_OLD.xlsx",
            "dtx": folder / "DTx_SalesCodes_30QX_V1_A.xlsx",
        }


def StubFile(path: Path):
    """What ui.upload hands its handler (NiceGUI 3's in-memory FileUpload)."""
    from nicegui.elements.upload_files import SmallFileUpload
    return SmallFileUpload(
        path.name,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        path.read_bytes())


def in_order(elements):
    """``user.find(...).elements`` is a set; creation order is page order."""
    return sorted(elements, key=lambda e: e.id)


def button(user: User, text: str) -> ui.button:
    """The one button whose label is exactly ``text``. ``find(text)`` matches
    substrings, so "Open" would also catch the "Open a family" select."""
    matches = [b for b in user.find(ui.button).elements if b.text == text]
    assert len(matches) == 1, f"expected one {text!r} button, found {len(matches)}"
    return matches[0]


async def press(user: User, text: str) -> None:
    """Click a button by exact label, the way the simulated user would —
    and refuse a disabled one, because that is the gate under test."""
    btn = button(user, text)
    assert btn.enabled, f"{text!r} is disabled"
    for listener in btn._event_listeners.values():
        if listener.type == "click":
            result = listener.handler(None)
            if inspect.isawaitable(result):
                await result
    await _settle()


async def _settle(seconds: float = 0.2) -> None:
    await asyncio.sleep(seconds)


async def wait_for(user: User, text: str, seconds: float = 30.0) -> None:
    """Poll until ``text`` is on the page, with a real timeout."""
    deadline = asyncio.get_event_loop().time() + seconds
    while True:
        try:
            await user.should_see(text, retries=1)
            return
        except AssertionError:
            if asyncio.get_event_loop().time() > deadline:
                raise
            await asyncio.sleep(0.25)


async def open_fed(user: User, files: dict) -> None:
    """Open the page and feed the four workbooks, in page order."""
    await user.open("/harness-complexity")
    await user.should_see("Analyze families")
    crossref, new, old, dtx = in_order(user.find(ui.upload).elements)
    await crossref.handle_uploads([StubFile(files["crossref"])])
    await new.handle_uploads([StubFile(files["new"])])
    await old.handle_uploads([StubFile(files["old"])])
    await dtx.handle_uploads([StubFile(files["dtx"])])
    # the upload handlers are async background tasks; each row confirms
    # what it received, and that confirmation is what the click waits on
    for key in ("crossref", "new", "old", "dtx"):
        await wait_for(user, f"✓ {files[key].name}")


async def open_analysed(user: User, files: dict) -> None:
    await open_fed(user, files)
    await press(user, "Analyze families")
    await wait_for(user, "Open a family")


async def open_ip(user: User, files: dict) -> None:
    await open_analysed(user, files)
    select = next(s for s in user.find(ui.select).elements
                  if s.props.get("label") == "Open a family")
    select.set_value("IP")
    await _settle()
    await press(user, "Open")
    await wait_for(user, "Workbench — IP")


class TestInputs:
    async def test_analyze_is_gated_until_both_required_files_arrive(self, user: User, files):
        await user.open("/harness-complexity")
        await user.should_see("Analyze families")
        act = button(user, "Analyze families")
        assert not act.enabled
        await user.should_see("Needs: the cross-reference workbook, the NEW master")
        crossref, new, _old, _dtx = in_order(user.find(ui.upload).elements)
        await crossref.handle_uploads([StubFile(files["crossref"])])
        await wait_for(user, f"✓ {files['crossref'].name}")
        await user.should_see("Needs: the NEW master")
        await new.handle_uploads([StubFile(files["new"])])
        await wait_for(user, f"✓ {files['new'].name}")
        assert act.enabled

    async def test_nothing_downstream_shows_before_an_analysis(self, user: User, files):
        await open_fed(user, files)
        assert button(user, "Analyze families").enabled
        await user.should_not_see("Open a family")
        await user.should_not_see("Workbench —")
        assert not button(user, "Generate .xlsm").enabled
        await user.should_see("Needs: an open worksheet")


class TestFamilies:
    async def test_the_families_arrive_with_the_old_vs_new_evidence(self, user: User, files):
        await open_analysed(user, files)
        await user.should_see("Affected by this change")
        # the OLD master lacks QF1, so every family carrying it is affected
        await user.should_see("codes changed")
        await user.should_see("Families analysed")
        await user.should_see("Affected families")

    async def test_open_is_gated_on_a_selected_family(self, user: User, files):
        await open_analysed(user, files)
        assert not button(user, "Open").enabled
        await user.should_see("Needs: a harness family")
        select = next(s for s in user.find(ui.select).elements
                      if s.props.get("label") == "Open a family")
        select.set_value("IP")
        await _settle()
        assert button(user, "Open").enabled


class TestWorkbench:
    async def test_ip_shows_the_planted_review_material(self, user: User, files):
        await open_ip(user, files)
        await wait_for(user, "Combined expressions")
        await user.should_see("QB1+(QA1/QA2)")
        await user.should_see("1 excluded")
        await user.should_see("equality — auto-resolved: QA1, QA2")
        await user.should_see("1 combined expressions to decide")
        await user.should_see("Exclude selected rows")

    async def test_generate_waits_for_a_harness_id_and_offers_a_button_not_a_push(self, user: User, files):
        await open_ip(user, files)
        await wait_for(user, "Combined expressions")
        assert not button(user, "Generate .xlsm").enabled
        await user.should_see("Needs: a Harness ID")
        harness_id = next(i for i in user.find(ui.input).elements
                          if i.props.get("label") == "Harness ID (manual)")
        harness_id.set_value("IP-001")
        await _settle()
        assert button(user, "Generate .xlsm").enabled
        await press(user, "Generate .xlsm")
        await wait_for(user, "Files generated")
        downloads = [b for b in user.find(ui.button).elements
                     if b.text.endswith(".xlsm")]
        assert downloads, "the generated file is offered as a download button"
        await user.should_see("1 files")
