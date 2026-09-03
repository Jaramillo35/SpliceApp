"""Circuit Health, driven as a user would drive it — no browser.

NiceGUI's simulated user opens the page, feeds the showcase files through
the real upload handlers, clicks the real buttons, and reads what rendered.

The showcase programme is invented data (2030QX). Its one planted defect is
pinned here: inline X350 ↔ Y350, cavity 2, a wire on BODY_LEFT and nothing
opposite on LIFTGATE — a Blocker (demo/README.md).
"""

from __future__ import annotations

import asyncio
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
        folder = out / "6_circuit_health"
        yield {
            "summary": folder / "Circuit_Summary_30QX_V1_A.xlsx",
            "complexities": sorted(folder.glob("2.- Harness_Complexity*.xlsx")),
        }


@pytest.fixture()
def baseline_path(tmp_path, monkeypatch) -> Path:
    """Every test gets its own disposition baseline, so nothing leaks between
    them — and nothing lands in the real data directory."""
    from nicegui_app.pages import circuit_health
    path = tmp_path / "baseline.json"
    monkeypatch.setattr(circuit_health, "BASELINE_PATH", path)
    return path


def StubFile(path: Path):
    """What ui.upload hands its handler."""
    from nicegui.elements.upload_files import SmallFileUpload
    return SmallFileUpload(
        path.name,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        path.read_bytes())


def in_order(elements):
    """``user.find(...).elements`` is a set; creation order is page order."""
    return sorted(elements, key=lambda e: e.id)


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


def bag(user: User) -> dict:
    """The page's per-client registry (gated actions, steps). It is keyed on
    the current client, so it is read from inside the client's context."""
    from nicegui_app import components as c
    with user.client:
        return c._bag()


def the_action(user: User, label: str):
    return next(a for a in bag(user)["actions"]
                if a.button.text == label and not a.button.is_deleted)


def steps(user: User) -> dict:
    return {s.name: (s.state, s.note) for s in bag(user)["steps"]}


async def open_loaded(user: User, files: dict) -> None:
    """Open the page and feed the showcase files through the upload rows."""
    summary, complexities = files["summary"], files["complexities"]
    await user.open("/circuit-health")
    await user.should_see("Inputs")
    summary_zone, complexity_zone = in_order(user.find(ui.upload).elements)
    await summary_zone.handle_uploads([StubFile(summary)])
    await complexity_zone.handle_uploads([StubFile(p) for p in complexities])
    await wait_for(user, f"✓ {summary.name}")
    await wait_for(user, f"✓ {len(complexities)} files received")


async def open_checked(user: User, files: dict) -> None:
    await open_loaded(user, files)
    user.find("Run health check").click()
    await wait_for(user, "Blocker")
    await wait_for(user, "Accepted variant")


class TestInputs:
    async def test_the_run_is_gated_until_both_inputs_exist(self, user: User, baseline_path, files):
        await user.open("/circuit-health")
        await user.should_see("Inputs")
        act = the_action(user, "Run health check")
        assert not act.button.enabled
        assert act.caption.text == "Needs: the Circuit Summary, at least one complexity file"
        await user.should_see("Nothing saved yet")

    async def test_the_gate_opens_once_the_files_land(self, user: User, baseline_path, files):
        await open_loaded(user, files)
        assert the_action(user, "Run health check").button.enabled


class TestRun:
    async def test_the_planted_blocker_is_found_and_the_inputs_fold(self, user: User, baseline_path, files):
        await open_checked(user, files)
        await user.should_see("Blockers open")
        await user.should_see("Loaded: Circuit_Summary_30QX_V1_A.xlsx + 4 complexity file(s)")
        await user.should_see("Change files")
        await user.should_see("Auto-cleared (2)")
        await user.should_see("4 harness(es) matched")

    async def test_the_step_bar_follows_the_state(self, user: User, baseline_path, files):
        await open_checked(user, files)
        state = steps(user)
        assert state["Inputs"][0] == "done"
        assert state["Review"][0] == "current" and state["Review"][1].endswith(" open")
        assert state["Sign-off"][0] == "blocked"
        assert not the_action(user, "Sign off this run").button.enabled


class TestDisposition:
    async def test_a_disposition_keeps_a_selection_and_lands_in_the_baseline(self, user: User, baseline_path, files):
        from nicegui_app import components as c
        await open_checked(user, files)
        pressed = [b for b in user.find(ui.button).elements
                   if b.props.get("aria-pressed") == "true"]
        assert pressed, "the first finding is selected as soon as the queue exists"
        user.find("Accepted variant").click()
        await _settle(0.5)
        await wait_for(user, "Dispositioned (1)")
        saved = json.loads(baseline_path.read_text())
        assert len(saved["dispositions"]) == 1
        verdicts = {d["verdict"] for d in saved["dispositions"].values()}
        assert verdicts == {"Accepted variant"}
        assert saved["saved_at"], "every save says when"
        assert "saved_by" in saved
        await user.should_see(f"Saved by {c.who() or 'unknown'}")
        # if any finding is still open it is selected — never nothing
        if not steps(user)["Review"][1].startswith("0 "):
            still = [b for b in user.find(ui.button).elements
                     if b.props.get("aria-pressed") == "true"]
            assert still, "the selection must move to the next finding, not vanish"
            await user.should_not_see("Select a finding to see its evidence.")
