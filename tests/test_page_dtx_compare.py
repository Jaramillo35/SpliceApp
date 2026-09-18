"""DTx Compare, driven as a user would drive it, on the showcase exports."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from demo import showcase

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(scope="module")
def files() -> dict:
    with tempfile.TemporaryDirectory(prefix="showcase_") as td:
        out = Path(td)
        showcase.build(out)
        folder = out / "4_dtx_compare"
        yield {"old": next(folder.glob("*_OLD.xlsx")),
               "new": next(folder.glob("*_NEW.xlsx")),
               "dtcr": next(folder.glob("DTCR_Report_*.xlsx"))}


def StubFile(path: Path):
    from nicegui.elements.upload_files import SmallFileUpload
    return SmallFileUpload(path.name, XLSX, path.read_bytes())


def in_order(elements):
    return sorted(elements, key=lambda e: e.id)


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


def _button(user: User, text: str):
    return next(b for b in user.find(ui.button).elements if b.text == text)


async def press(user: User, text: str) -> None:
    """Click the button whose label is exactly ``text``.

    ``user.find(text).click()`` matches every element *containing* the text,
    so a caption that mentions a button swallows the click. A button is
    pressed by its own label.
    """
    import inspect
    btn = _button(user, text)
    assert btn.enabled, f"{text!r} is disabled"
    for listener in btn._event_listeners.values():
        if listener.type == "click":
            out = listener.handler(None)
            if inspect.isawaitable(out):
                await out
    await asyncio.sleep(0.2)


async def test_the_gate_names_what_is_missing_then_opens(user: User, files):
    await user.open("/dtx-compare")
    await user.should_see("Needs: OLD DTx, NEW DTx")
    for group in ("Required", "Optional", "Other outputs"):
        await user.should_see(group)
    assert not _button(user, "Run compare").enabled
    assert not _button(user, "DTCR Matching only").enabled
    old, new, dtcr = in_order(user.find(ui.upload).elements)
    await old.handle_uploads([StubFile(files["old"])])
    await new.handle_uploads([StubFile(files["new"])])
    await wait_for(user, f"✓ {files['new'].name}")
    assert _button(user, "Run compare").enabled, "the DTCR report is optional"
    assert _button(user, "PreOrder list only").enabled, "PreOrder needs only OLD and NEW"
    await user.should_see("Needs: DTCR report")           # matching only still wants it
    assert not _button(user, "DTCR Matching only").enabled
    await dtcr.handle_uploads([StubFile(files["dtcr"])])
    await wait_for(user, f"✓ {files['dtcr'].name}")
    assert _button(user, "DTCR Matching only").enabled


async def test_without_the_dtcr_report_the_compare_says_so(user: User, files):
    await user.open("/dtx-compare")
    old, new, _dtcr = in_order(user.find(ui.upload).elements)
    await old.handle_uploads([StubFile(files["old"])])
    await new.handle_uploads([StubFile(files["new"])])
    await wait_for(user, f"✓ {files['new'].name}")
    await press(user, "Run compare")
    await wait_for(user, "Built without a DTCR report")
    await user.should_see("DTx_Change_Report_")
    await user.should_see("Change compare — no DTCR report")
    await user.should_see("Change workbook")
    assert not any("DTCR_Matching_Report_" in (lbl.text or "")
                   for lbl in user.find(ui.label).elements)


async def test_matching_only_gives_the_secr_database_its_input(user: User, files):
    await user.open("/dtx-compare")
    old, new, dtcr = in_order(user.find(ui.upload).elements)
    await old.handle_uploads([StubFile(files["old"])])
    await new.handle_uploads([StubFile(files["new"])])
    await dtcr.handle_uploads([StubFile(files["dtcr"])])
    await wait_for(user, f"✓ {files['dtcr'].name}")
    await press(user, "DTCR Matching only")
    await wait_for(user, "Matched to a harness family")
    await user.should_see("DTCR_Matching_Report_")
    # its own result, not a compare that lost its numbers
    await user.should_see("DTCR matching report")
    await user.should_see("For the SECR Database")
    await user.should_not_see("Added circuits")
    await user.should_not_see("Change workbook")


async def test_the_compare_finds_the_planted_added_circuits(user: User, files):
    await user.open("/dtx-compare")
    old, new, dtcr = in_order(user.find(ui.upload).elements)
    await old.handle_uploads([StubFile(files["old"])])
    await new.handle_uploads([StubFile(files["new"])])
    await dtcr.handle_uploads([StubFile(files["dtcr"])])
    await wait_for(user, f"✓ {files['dtcr'].name}")
    await press(user, "Run compare")
    await wait_for(user, "Added circuits")
    # the OLD export is missing QK106 and QK702 (demo/README.md)
    labels = {lbl.text for lbl in user.find(ui.label).elements}
    assert "2" in labels
    # three files: the change workbook (with its DTCR Matching sheet) and the
    # DTCR Matching Report as a separate download
    await user.should_see("DTx_Change_Report_")
    await user.should_see("DTCR_Matching_Report_")
    # two deliverables, each saying what it is and who it is for
    await user.should_see("Change compare — tagged by DTCR")
    await user.should_see("Change workbook")
    await user.should_see("DTCR Matching Report")
    await user.should_see("For the SECR Database")


async def test_the_matching_report_is_handed_over_undressed(user: User, files, monkeypatch):
    """It is the SECR Database's input. The workbook dresser adds a Read Me
    sheet and restyles headers for the toolkit's own reports; another tool's
    input goes out exactly as the engine wrote it."""
    from nicegui_app import components
    handed: list = []
    monkeypatch.setattr(components, "deliver",
                        lambda data, filename, *, dress=True: handed.append((filename, dress)))
    await user.open("/dtx-compare")
    old, new, dtcr = in_order(user.find(ui.upload).elements)
    await old.handle_uploads([StubFile(files["old"])])
    await new.handle_uploads([StubFile(files["new"])])
    await dtcr.handle_uploads([StubFile(files["dtcr"])])
    await wait_for(user, f"✓ {files['dtcr'].name}")
    await press(user, "Run compare")
    await wait_for(user, "Change workbook")
    for btn in list(user.find(ui.button).elements):
        if btn.text.startswith(("DTx_Change_Report_", "DTCR_Matching_Report_")):
            await press(user, btn.text)
    by_prefix = {name.split("_Report_")[0]: dress for name, dress in handed}
    assert by_prefix == {"DTx_Change": True, "DTCR_Matching": False}
