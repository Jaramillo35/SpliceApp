"""Inline Comment Carryover, driven as a user would drive it — no browser.

Feeds the invented old and new reports from ``fixtures_inline_reports``
through the real upload handlers, presses the real buttons, and checks the
three things the page is for: the gate holds while rows are undecided, the
bulk decisions clear it, and the download is the report untouched by the
toolkit's workbook dressing — an inline report has to come back in exactly
its own format.

What these cannot reach is AG Grid's client-side cell editing; the decisions
it records go through ``Carryover.decide``, which ``test_inline_carryover``
covers.
"""

from __future__ import annotations

import asyncio
import inspect
import io
import tempfile
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User
from openpyxl import load_workbook

from tests import fixtures_inline_reports as fx


@pytest.fixture(scope="module")
def files() -> dict:
    with tempfile.TemporaryDirectory(prefix="inline_reports_") as td:
        folder = Path(td)
        old = folder / "OLD_Inline_Report.xlsx"
        new = folder / "NEW_Inline_Report.xlsx"
        old.write_bytes(fx.old_report())
        new.write_bytes(fx.new_report())
        yield {"old": old, "new": new}


def StubFile(path: Path):
    from nicegui.elements.upload_files import SmallFileUpload
    return SmallFileUpload(
        path.name,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        path.read_bytes())


def in_order(elements):
    return sorted(elements, key=lambda e: e.id)


def button(user: User, text: str) -> ui.button:
    matches = [b for b in user.find(ui.button).elements if b.text == text]
    assert len(matches) == 1, f"expected one {text!r} button, found {len(matches)}"
    return matches[0]


async def press(user: User, text: str) -> None:
    btn = button(user, text)
    assert btn.enabled, f"{text!r} is disabled"
    for listener in btn._event_listeners.values():
        if listener.type == "click":
            result = listener.handler(None)
            if inspect.isawaitable(result):
                await result
    await asyncio.sleep(0.2)


async def wait_for(user: User, text: str, seconds: float = 30.0) -> None:
    deadline = asyncio.get_event_loop().time() + seconds
    while True:
        try:
            await user.should_see(text, retries=1)
            return
        except AssertionError:
            if asyncio.get_event_loop().time() > deadline:
                raise
            await asyncio.sleep(0.25)


async def open_matched(user: User, files: dict) -> None:
    await user.open("/inline-comments")
    await user.should_see("Match comments")
    old, new = in_order(user.find(ui.upload).elements)
    await old.handle_uploads([StubFile(files["old"])])
    await new.handle_uploads([StubFile(files["new"])])
    await wait_for(user, f"✓ {files['old'].name}")
    await wait_for(user, f"✓ {files['new'].name}")
    await press(user, "Match comments")
    await wait_for(user, "Still to decide")


class TestInputs:
    async def test_match_waits_for_both_reports(self, user: User, files):
        await user.open("/inline-comments")
        await user.should_see("Match comments")
        assert not button(user, "Match comments").enabled
        await user.should_see("the OLD report")
        old, _new = in_order(user.find(ui.upload).elements)
        await old.handle_uploads([StubFile(files["old"])])
        await wait_for(user, f"✓ {files['old'].name}")
        assert not button(user, "Match comments").enabled


class TestReview:
    async def test_the_result_is_counted_and_nothing_is_dropped(self, user: User, files):
        await open_matched(user, files)
        for label in ("Copied as-is", "Sales code changed", "Row changed",
                      "Still to decide", "Comments with no row"):
            await user.should_see(label)
        await user.should_see("X903A - Y903A: in the old report but not the new one")
        await user.should_see("Comments with no row in the new report (2)")

    async def test_identical_rows_start_hidden(self, user: User, files):
        await open_matched(user, files)
        await user.should_see("Show the 5 identical row(s) copied without asking")

    async def test_the_gate_holds_until_every_row_is_decided(self, user: User, files):
        await open_matched(user, files)
        assert not button(user, "Write the commented report").enabled
        await user.should_see("a decision on 6 row(s)")
        await press(user, "Copy old comment on 2 sales-code change(s)")
        await wait_for(user, "a decision on 4 row(s)")
        assert not button(user, "Write the commented report").enabled
        await press(user, "Leave 4 changed row(s) blank")
        await wait_for(user, "Write the commented report")
        assert button(user, "Write the commented report").enabled


class TestGenerate:
    async def test_the_download_is_the_report_in_its_own_format(
            self, user: User, files, monkeypatch):
        """``dress=False`` is the point: the toolkit's workbook dressing adds a
        Read Me sheet, which would make this no longer an inline report."""
        from nicegui_app import components
        handed: dict = {}

        def capture(data, filename, *, dress=True):
            handed.update(data=data, filename=filename, dress=dress)

        monkeypatch.setattr(components, "deliver", capture)
        await open_matched(user, files)
        await press(user, "Copy old comment on 2 sales-code change(s)")
        await press(user, "Leave 4 changed row(s) blank")
        await press(user, "Write the commented report")
        await wait_for(user, "NEW_Inline_Report_commented.xlsx")
        await press(user, "NEW_Inline_Report_commented.xlsx")

        assert handed["filename"] == "NEW_Inline_Report_commented.xlsx"
        assert handed["dress"] is False
        wb = load_workbook(io.BytesIO(handed["data"]))
        assert wb.sheetnames == load_workbook(io.BytesIO(files["new"].read_bytes())).sheetnames
        ws = wb["X901A - Y901A"]
        assert ws.cell(2, 1).value == "WIRE TYPE OK"
        assert ws.cell(3, 1).value == "SUFFIX OK"
        assert ws.cell(4, 1).value is None          # changed row, left blank
        assert ws.cell(11, 1).value == "New view"   # its own comment kept
