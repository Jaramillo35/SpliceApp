"""HRN Chart Builder, driven as a user would drive it — no browser.

The page is a converter: files in, workbooks out. The showcase ships one
HRN + CSV + CMP triple for it; the three pair by stem, the gate opens once
a pair exists, and one workbook comes back. With a CMP present every
connector matches, so the workbook comes back clean.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from demo import showcase


@pytest.fixture(scope="module")
def files() -> list[Path]:
    """The showcase triple, built fresh — only the builder is committed."""
    with tempfile.TemporaryDirectory(prefix="showcase_") as td:
        out = Path(td)
        showcase.build(out)
        yield sorted((out / "7_hrn_chart_builder").iterdir())


def StubFile(path: Path):
    """What ui.upload hands its handler. NiceGUI 3 insists on its own
    FileUpload type; SmallFileUpload is the in-memory one it uses itself.
    The .hrn / .csv / .cmp files are plain text."""
    from nicegui.elements.upload_files import SmallFileUpload
    return SmallFileUpload(path.name, "text/plain", path.read_bytes())


def in_order(elements):
    """``user.find(...).elements`` is a set; creation order is the page
    order. The page has two upload zones — the inputs and the supplier
    override — and the inputs zone is the first one built."""
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


def _today() -> str:
    from datetime import date
    return date.today().strftime("%m%d%Y")


def _build_button(user: User) -> ui.button:
    return next(e for e in in_order(user.find("Build charts").elements)
                if isinstance(e, ui.button))


class TestConverter:
    async def test_the_gate_is_closed_until_a_pair_exists(self, user: User):
        await user.open("/hrn-chart")
        await user.should_see("Drop files to see how they pair.")
        await user.should_see("Needs: an HRN + Matrix CSV pair")
        assert not _build_button(user).enabled

    async def test_the_triple_pairs_and_builds_one_workbook(self, user: User, files):
        assert len(files) == 3, [p.name for p in files]
        await user.open("/hrn-chart")
        await user.should_see("Build charts")
        zone = in_order(user.find(ui.upload).elements)[0]
        await zone.handle_uploads([StubFile(p) for p in files])
        await wait_for(user, "✓ 3 files received")
        await user.should_not_see("Drop files to see how they pair.")
        assert _build_button(user).enabled

        user.find("Build charts").click()
        # the pairing preview already names the output .xlsx, so the verdict
        # chip is what proves the build ran — the showcase triple is clean
        await wait_for(user, "clean")
        # the shipped supplier list is an .xlsx button too — match the chart
        workbooks = [b for b in user.find(ui.button).elements
                     if "_Chart_" in b.text and b.text.endswith(".xlsx")]
        assert len(workbooks) == 2, "one row download plus the result panel's action"
        assert {b.text for b in workbooks} == {"IP_2030QX_Chart_" + _today() + ".xlsx"}
