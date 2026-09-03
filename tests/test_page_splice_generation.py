"""Splice Generation, driven as a user would drive it — no browser.

The page was rewritten onto the converter archetype; this pins the path
that matters: drop the workbook, the primary un-gates, run, and the four
tables land in the result panel.

Input: the sample workbook the page itself offers for download
(``assets/downloads/Z913_example_input.xlsx``). The showcase's
``5_splice_generation/Splice_Input_30QX_V1_A.xlsx`` is *not* usable here —
``demo.showcase.write_splice_input`` reuses the shared CIRCUITS list, which
carries the deliberately malformed ``QB1-QA1`` on QK109 (planted for the
Circuit Applicability integrity step), and ``splice.splice_gen.run_analysis``
refuses the whole workbook with ``ExpressionSyntaxError``. Once the showcase
writes a clean splice input, point ``WORKBOOK`` at it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui
from nicegui.testing import User

WORKBOOK = Path(__file__).resolve().parents[1] / "assets" / "downloads" / "Z913_example_input.xlsx"


def StubFile(path: Path):
    """What ui.upload hands its handler. NiceGUI 3 insists on its own
    FileUpload type; SmallFileUpload is the in-memory one it uses itself."""
    from nicegui.elements.upload_files import SmallFileUpload
    return SmallFileUpload(
        path.name,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        path.read_bytes())


def in_order(elements):
    """``user.find(...).elements`` is a set; creation order is the page order."""
    return sorted(elements, key=lambda e: e.id)


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


def run_button(user: User) -> ui.button:
    return next(e for e in in_order(user.find("Run analysis").elements)
                if isinstance(e, ui.button))


async def test_drop_the_workbook_run_and_the_tables_appear(user: User):
    assert WORKBOOK.exists(), WORKBOOK
    await user.open("/splice-generation")
    await user.should_see("Inputs")
    assert not run_button(user).enabled, "the primary is gated until the workbook exists"
    await user.should_see("Needs: Splice input workbook")

    zone = in_order(user.find(ui.upload).elements)[0]
    await zone.handle_uploads([StubFile(WORKBOOK)])
    await wait_for(user, f"✓ {WORKBOOK.name}")
    assert run_button(user).enabled

    user.find("Run analysis").click()
    await wait_for(user, "Configurations (")
    await user.should_see("Generated connections (")
    await user.should_see("Harness print matrix (")
    await user.should_see("OptionPerCkt (as read) (")
    await user.should_see("Wiring_Harness_Output_")
    await user.should_see("Sales-code editor")
