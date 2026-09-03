"""VBOM Risk Matrix, driven as a user would drive it — no browser.

The showcase programme (2030 QX) pins the numbers: a BuildSpec with eight
VINs and eight complexity files produce thirteen review cases, and the DEFE
stays withheld until every one has a decision. What this guards is the
workbench shape — the gate really gates — and the study's F7 fix: a
resolution is written through the store the moment it is made, and a
regenerated bundle finds it again.
"""

from __future__ import annotations

import asyncio
import inspect
import json
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
        folder = out / "2_vbom_risk_matrix"
        yield {
            "spec": folder / "2030_QX_BuildSpec_V1A.xlsx",
            "complexities": sorted(folder.glob("2.- Harness_Complexity*.xlsx")),
        }


def StubFile(path: Path):
    """What ui.upload hands its handler (NiceGUI 3's in-memory FileUpload)."""
    from nicegui.elements.upload_files import SmallFileUpload
    return SmallFileUpload(
        path.name,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        path.read_bytes())


@pytest.fixture()
def store_path(tmp_path, monkeypatch) -> Path:
    """Every test gets its own review store, so nothing leaks between them."""
    from splice.vbom import review_store
    path = tmp_path / "review.json"
    monkeypatch.setattr(review_store, "STORE_PATH", path)
    return path


def in_order(elements):
    """``user.find(...).elements`` is a set; creation order is the page order."""
    return sorted(elements, key=lambda e: e.id)


def marked(user: User, prefix: str) -> list:
    """Elements whose marker starts with ``prefix``, in page order."""
    return in_order(e for e in user.find(ui.element).elements
                    if any(m.startswith(prefix) for m in e._markers))


async def _settle(seconds: float = 0.2) -> None:
    await asyncio.sleep(seconds)


async def wait_for(user: User, text: str, seconds: float = 60.0) -> None:
    """Poll until ``text`` is on the page, with a real timeout — the VBOM
    workflow formats every sheet of every workbook and takes a while."""
    deadline = asyncio.get_event_loop().time() + seconds
    while True:
        try:
            await user.should_see(text, retries=1)
            return
        except AssertionError:
            if asyncio.get_event_loop().time() > deadline:
                raise
            await asyncio.sleep(0.25)


async def click(element: ui.element) -> None:
    """Click one element by its own handler. ``user.find("Resolve").click()``
    would press every Resolve button on the page at once."""
    listeners = [l for l in element._event_listeners.values() if l.type == "click"]
    assert listeners, f"{element} handles no click"
    result = listeners[0].handler(None)
    if inspect.isawaitable(result):
        await result
    await _settle()


def button(user: User, text: str) -> ui.button:
    return next(b for b in in_order(user.find(ui.button).elements) if b.text == text)


def button_starting(user: User, prefix: str) -> ui.button:
    return next(b for b in in_order(user.find(ui.button).elements)
                if b.text.startswith(prefix))


async def open_ready(user: User, files: dict) -> None:
    """Open the page, name the programme, feed the showcase files."""
    spec, complexities = files["spec"], files["complexities"]
    await user.open("/vbom")
    await user.should_see("Generate VBOM bundle")
    assert not button(user, "Generate VBOM bundle").enabled, "nothing loaded, the gate is shut"
    marked(user, "vbom-my")[0].set_value("30")
    marked(user, "vbom-program")[0].set_value("QX")
    marked(user, "vbom-source")[0].set_value("BuildSpec")
    spec_zone, complexity_zone = in_order(user.find(ui.upload).elements)
    await spec_zone.handle_uploads([StubFile(spec)])
    await complexity_zone.handle_uploads([StubFile(p) for p in complexities])
    # the upload handlers are async background tasks; the zones confirm
    # what they received, and that confirmation is what the click waits on
    await wait_for(user, f"✓ {spec.name}")
    await wait_for(user, f"✓ {len(complexities)} files received")


async def open_generated(user: User, files: dict) -> None:
    await open_ready(user, files)
    assert button(user, "Generate VBOM bundle").enabled, "every input is present, the gate opens"
    user.find("Generate VBOM bundle").click()
    await wait_for(user, "0 of 13 review cases resolved", seconds=180)


class TestInputs:
    async def test_the_gate_names_what_is_missing_until_everything_is_there(
            self, user: User, store_path, files):
        await user.open("/vbom")
        await user.should_see("Needs: model year, program, the DoAll / BuildSpec "
                              "file, at least one complexity file")
        await open_ready(user, files)
        assert button(user, "Generate VBOM bundle").enabled
        await user.should_not_see("Needs: model year")


class TestGenerate:
    async def test_eight_vins_produce_thirteen_review_cases_and_withhold_the_defe(
            self, user: User, store_path, files):
        await open_generated(user, files)
        await user.should_see("13 unresolved")
        await user.should_see("5 files")
        await user.should_see("VBOM_Risk_Matrix_Bundle.zip")
        defe = button_starting(user, "Generate 30_QX_VBOM_Template_for_DEFE")
        assert not defe.enabled, "the DEFE is withheld until the gate is clear"
        await user.should_see("Needs: 13 unresolved case(s)")


class TestReview:
    async def test_resolving_a_case_is_saved_at_once_and_counts_down(
            self, user: User, store_path, files):
        await open_generated(user, files)
        await user.should_see("Nothing saved yet")
        select = marked(user, "vbom-pn-")[0]
        assert select.value, "the engine's recommendation is pre-selected"
        chosen = select.options[0]
        select.set_value(chosen)
        # the first case's Resolve button: the pairs are laid out in case order
        resolve = next(b for b in in_order(user.find(ui.button).elements)
                       if b.text == "Resolve" and b.enabled)
        await click(resolve)
        await wait_for(user, "1 of 13 review cases resolved")
        await user.should_see("12 unresolved")
        await user.should_see("Needs: 12 unresolved case(s)")
        await user.should_see("rev 1")
        saved = json.loads(store_path.read_text())
        assert saved["revision"] == 1
        (key, record), = saved["resolutions"].items()
        assert key.startswith("30_QX|") and key.count("|") == 2
        assert record["pn"] == chosen

    async def test_a_regenerated_bundle_restores_a_decision_left_earlier(
            self, user: User, store_path, files):
        """The F7 fix: the judgement outlives the page."""
        from splice.vbom import review_store
        await open_generated(user, files)
        resolve = next(b for b in in_order(user.find(ui.button).elements)
                       if b.text == "Resolve" and b.enabled)
        await click(resolve)
        await wait_for(user, "1 of 13 review cases resolved")
        (key,) = json.loads(store_path.read_text())["resolutions"]
        _tag, rid = key.split("|", 1)
        # another session changed that decision in the meantime
        review_store.save({"resolutions": review_store.remember(
            {}, "30", "QX", rid, "N/A", "left earlier", by="A.B.")},
            store_path, by="A.B.")
        user.find("Generate VBOM bundle").click()
        await _settle(1.0)
        await wait_for(user, "1 of 13 review cases resolved", seconds=180)
        await user.should_see("Saved by A.B.")
        await user.should_see("rev 2")
        await user.should_see("resolved · N/A")
        await user.should_see("Decided by A.B.")
        assert marked(user, "vbom-pn-")[0].value == "N/A"

    async def test_a_stale_save_is_refused_and_says_who_moved_it(
            self, user: User, store_path, files):
        from splice.vbom import review_store
        await open_generated(user, files)
        # someone else saved after this page loaded its revision
        review_store.save({"resolutions": {}}, store_path, by="C.D.")
        resolve = next(b for b in in_order(user.find(ui.button).elements)
                       if b.text == "Resolve" and b.enabled)
        await click(resolve)
        await user.should_see("Not saved — this review was changed by C.D.")
        await user.should_see("0 of 13 review cases resolved")
        assert json.loads(store_path.read_text())["saved_by"] == "C.D."
