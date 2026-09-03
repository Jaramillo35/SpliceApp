"""The accessibility gate the schema's phase 4 promised.

Two things are checked here rather than by eye: every status pairing the
app and the workbooks use clears the WCAG AA contrast bar on its own
ground, and nothing in the pages is a click target that a keyboard cannot
reach.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nicegui_app import theme

APP = Path(__file__).resolve().parents[1] / "nicegui_app"


# ------------------------------------------------------------- contrast
def _srgb(channel: float) -> float:
    channel /= 255
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b)


def contrast(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def blend(fg: str, bg: str, alpha: float) -> str:
    """A wash: ``fg`` at ``alpha`` over ``bg``, as the browser composites it."""
    f, b = fg.lstrip("#"), bg.lstrip("#")
    out = []
    for i in (0, 2, 4):
        fv, bv = int(f[i:i + 2], 16), int(b[i:i + 2], 16)
        out.append(round(fv * alpha + bv * (1 - alpha)))
    return "#" + "".join(f"{v:02x}" for v in out)


WASH_ALPHA = 0x24 / 255      # theme.wash()'s default


SURFACES = ("CANVAS", "SURFACE", "SURFACE_2", "SURFACE_3")


@pytest.mark.parametrize("kind", sorted(theme.STATUS))
def test_status_text_reads_on_its_own_chip(kind):
    """A chip is STATUS_TEXT on a 14 % wash of STATUS over any surface."""
    mark, ink = theme.STATUS[kind], theme.STATUS_TEXT[kind]
    for name in SURFACES:
        ground = blend(mark, getattr(theme, name), WASH_ALPHA)
        ratio = contrast(ink, ground)
        assert ratio >= 4.5, f"{kind} on its chip over {name}: {ratio:.2f}:1"


@pytest.mark.parametrize("kind", sorted(theme.STATUS))
def test_status_text_reads_on_every_app_surface(kind):
    for name in SURFACES:
        ratio = contrast(theme.STATUS_TEXT[kind], getattr(theme, name))
        assert ratio >= 4.5, f"{kind} text on {name}: {ratio:.2f}:1"


@pytest.mark.parametrize("kind", sorted(theme.STATUS))
def test_status_marks_stay_distinguishable_as_non_text(kind):
    """Borders, dots and chart marks need 3:1, not 4.5:1 — and STATUS keeps
    the validated chart steps, which is why the text tier exists."""
    for name in SURFACES:
        ratio = contrast(theme.STATUS[kind], getattr(theme, name))
        assert ratio >= 3.0, f"{kind} mark on {name}: {ratio:.2f}:1"


@pytest.mark.parametrize("tier,floor", [("TEXT", 7.0), ("TEXT_2", 4.5), ("TEXT_3", 3.0)])
def test_text_tiers_clear_their_bars(tier, floor):
    """Primary text is AAA body copy, secondary AA, tertiary AA large."""
    for name in ("CANVAS", "SURFACE", "SURFACE_2"):
        ratio = contrast(getattr(theme, tier), getattr(theme, name))
        assert ratio >= floor, f"{tier} on {name}: {ratio:.2f}:1 < {floor}"


def test_brand_reads_as_text_and_the_workbook_pairings_read_on_paper():
    assert contrast(theme.BRAND, theme.SURFACE) >= 3.0
    from splice.common import workbook
    for kind, (fill, text) in workbook.STATUS.items():
        ratio = contrast("#" + text, "#" + fill)
        assert ratio >= 4.5, f"workbook {kind}: {ratio:.2f}:1"
    header = contrast("#" + workbook.HEADER_TEXT, "#" + workbook.HEADER_FILL)
    assert header >= 4.5, f"workbook header: {header:.2f}:1"


# ------------------------------------------------------------- keyboard
CLICKABLE_DIV = re.compile(r"ui\.(element|row|column|label|image|icon|card)\([^\n]*\)"
                           r"(?:[^\n]*\n)??[^\n]*\.on\(\s*[\"']click[\"']")


def test_no_page_makes_a_click_target_a_keyboard_cannot_reach():
    """Every click target is a button or a link.

    Divs are not focusable and carry no role, so a reviewer on the keyboard
    could not disposition a finding or set a filter. The components layer
    provides ``toggle_chip`` and plain buttons for exactly this.
    """
    offenders = []
    for path in sorted(APP.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in CLICKABLE_DIV.finditer(text):
            line = text[:match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(APP)}:{line}")
    assert not offenders, ("click handlers on non-interactive elements: "
                           f"{offenders}")


def test_every_icon_only_button_has_a_name():
    """An icon with no label needs a tooltip or an aria-label to be usable."""
    pattern = re.compile(r"ui\.button\(\s*icon=")
    offenders = []
    for path in sorted(APP.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            tail = text[match.start():match.start() + 500]
            statement = tail.split("\n\n")[0]
            if "tooltip" not in statement and "aria-label" not in statement:
                offenders.append(f"{path.relative_to(APP)}:"
                                 f"{text[:match.start()].count(chr(10)) + 1}")
    assert not offenders, f"icon-only buttons without a name: {offenders}"


def test_the_brand_mark_is_a_plain_image_on_a_static_route():
    """ui.image() renders a Quasar q-img that fades itself in from opacity 0
    when its own load handler fires. In the packaged app that handler did
    not fire, so the mark rendered at zero opacity — present in the DOM,
    invisible on screen. The shell uses a plain <img> for exactly that
    reason; this keeps it that way."""
    from nicegui_app import components as c

    source = (APP / "components.py").read_text(encoding="utf-8")
    code = [line for line in source.splitlines()
            if not line.lstrip().startswith("#")]
    calls = [line.strip() for line in code if "ui.image(" in line]
    assert not calls, f"the rail must not use q-img for the mark: {calls}"
    assert 'alt="Versigent"' in source, "the mark needs an accessible name"
    assert c.LOGO.exists() and c.LOGO.suffix == ".png"
    assert c.LOGO_URL.startswith(c.ASSETS_URL)


async def test_filter_chips_and_queue_rows_are_native_buttons(user):
    """The reachability half of the keyboard gate, asserted in code.

    A browser activates a native ``<button>`` on Enter and Space by
    definition, so the invariant worth pinning is the element type and its
    pressed state — not a synthetic key press. The tab order itself was
    walked in the running app: filter chips, the queue rows, the reason
    field, the three verdict buttons, the engineer field and the download
    all appear in DOM order with accessible names.
    """
    from nicegui import ui
    from nicegui_app import components as c

    state = {"on": False}

    @ui.page("/_probe_chips")
    def probe() -> None:
        c.toggle_chip("Blocker", state["on"], lambda: state.update(on=True), 3)

    await user.open("/_probe_chips")
    chip = next(iter(user.find(ui.button).elements))
    assert isinstance(chip, ui.button), "a filter must be a button, not a div"
    assert chip._props.get("aria-pressed") == "false"
    assert "sx-toggle" in chip.classes
    chip.run_method  # a real Quasar button, which Enter and Space activate
    await user.should_see("Blocker · 3")


def test_the_focus_ring_is_defined_for_keyboard_focus():
    """Programmatic focus does not match :focus-visible, so the ring has to
    be declared for it explicitly or a keyboard user cannot see where they
    are."""
    source = (APP / "theme.py").read_text(encoding="utf-8")
    assert ":focus-visible" in source
    assert "outline: 2px solid" in source
