"""The token layer is enforceable, or it is a suggestion.

Every colour and every text size a page uses comes from ``theme.py``; the
page registry is the one list the rail, the Overview and the feedback
dialog read; and the gated action really gates.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "nicegui_app"
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
RGBA = re.compile(r"rgba?\(")
SUB_FLOOR = re.compile(r"text-\[(?:[1-9]|1[01])px\]")


def _sources():
    for path in APP.rglob("*.py"):
        if path.name == "theme.py":
            continue
        yield path, path.read_text(encoding="utf-8")


def test_no_colour_literal_outside_theme():
    offenders = [f"{p.relative_to(APP)}:{i}" for p, src in _sources()
                 for i, line in enumerate(src.splitlines(), 1)
                 if HEX.search(line) or RGBA.search(line)]
    assert not offenders, f"colour literals belong in theme.py: {offenders}"


def test_twelve_pixels_is_the_floor():
    offenders = [f"{p.relative_to(APP)}:{i}" for p, src in _sources()
                 for i, line in enumerate(src.splitlines(), 1)
                 if SUB_FLOOR.search(line)]
    assert not offenders, f"text below 12px: {offenders}"


def test_every_registered_page_has_a_route():
    import nicegui_app.main  # noqa: F401  (importing registers the routes)
    from nicegui import app
    from nicegui_app import components as c

    paths = {getattr(r, "path", None) for r in app.routes}
    for page in (*c.PAGES, c.OVERVIEW, c.ADMIN):
        assert page.route in paths, f"{page.label} points at an unregistered route"
    assert len({p.route for p in c.PAGES}) == len(c.PAGES)
    assert all(p.family in c.FAMILIES for p in c.PAGES)


async def test_frame_table_announces_its_cap(user):
    from nicegui import ui
    from nicegui_app import components as c

    @ui.page("/_probe_table")
    def probe() -> None:
        rows = [{"circuit": f"QK{i:03d}", "count": i} for i in range(40)]
        c.frame_table(rows, cap=10)

    await user.open("/_probe_table")
    await user.should_see("Showing 10 of 40 rows")
    table = next(iter(user.find(ui.table).elements))
    assert len(table.rows) == 10
    assert table.columns[0]["label"] == "Circuit"


async def test_action_gates_until_its_inputs_exist(user):
    from nicegui import ui
    from nicegui_app import components as c

    have: dict = {}
    holder: dict = {}

    @ui.page("/_probe_action")
    def probe() -> None:
        holder["act"] = c.action(
            "Run compare", lambda: None,
            needs=lambda: [n for n in ("OLD DTx", "NEW DTx") if n not in have])

    await user.open("/_probe_action")
    act = holder["act"]
    assert not act.button.enabled
    assert act.caption.text == "Needs: OLD DTx, NEW DTx"
    have["OLD DTx"] = True
    act.check()
    assert act.caption.text == "Needs: NEW DTx"
    have["NEW DTx"] = True
    act.check()
    assert act.button.enabled
    assert not act.caption.visible
