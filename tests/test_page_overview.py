"""The Overview is a dashboard read from what the app already keeps."""

from __future__ import annotations

import json


async def test_overview_shows_continue_attention_and_every_family(user, tmp_path, monkeypatch):
    from splice.common import activity
    from nicegui_app import components as c

    path = tmp_path / "activity.jsonl"
    monkeypatch.setattr(activity, "ACTIVITY_PATH", path)
    activity.record("DTx Compare", "/dtx-compare", "Compare workbook ready",
                    by="MJ", context="2030QX · V1_A", path=path)

    await user.open("/")
    await user.should_see("Continue")
    await user.should_see("Needs attention")
    await user.should_see("Compare workbook ready")
    await user.should_see("2030QX · V1_A")
    for family in c.FAMILIES:
        await user.should_see(family)
    for page in c.PAGES:
        await user.should_see(page.label)


def test_activity_feed_is_bounded_and_newest_first(tmp_path):
    from splice.common import activity
    path = tmp_path / "a.jsonl"
    for i in range(3):
        activity.record("T", "/t", f"run {i}", path=path)
    rows = activity.recent(10, path)
    assert [r["summary"] for r in rows] == ["run 2", "run 1", "run 0"]
    path.write_text(path.read_text() + "{not json\n")
    assert activity.recent(10, path)[0]["summary"] == "run 2"
    assert json.loads(path.read_text().splitlines()[0])["tool"] == "T"


async def test_attention_lines_are_sentences_not_chips(user, tmp_path, monkeypatch):
    """A chip is a word. The attention list carries sentences, so it must
    render them as notes — a pill wrapping to four lines becomes a blob at
    narrow widths."""
    from nicegui import ui
    from nicegui_app import components as c

    await user.open("/")
    await user.should_see("Needs attention")
    long_chip_labels = [
        lbl.text for lbl in user.find(ui.label).elements
        if lbl.text and len(lbl.text) > 40
        and "font-semibold" in " ".join(lbl.classes) and "text-xs" in " ".join(lbl.classes)
    ]
    assert not long_chip_labels, f"sentences rendered as chips: {long_chip_labels}"
