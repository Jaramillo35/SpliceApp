"""Constants and the small pieces more than one card draws."""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme

ROW_H = 34          # px; every cell in a row shares it so the lines align
GRID = "grid-template-columns: 1.1fr 64px 1.25fr 1.5fr"
GREEN = theme.STATUS["ok"]
RED = theme.STATUS["blocker"]

VERDICT_KIND = {
    "unconditional": "ok", "all builds": "ok", "variant": "info",
    "never built": "blocker", "no complexity": "review",
}


def line(matched: bool) -> str:
    """The connector between a family and its complexity file."""
    if matched:
        return (f'<svg width="100%" height="{ROW_H}" aria-label="connected">'
                f'<line x1="0" y1="{ROW_H//2}" x2="100%" y2="{ROW_H//2}" '
                f'stroke="{GREEN}" stroke-width="2"/>'
                f'<circle cx="6" cy="{ROW_H//2}" r="3" fill="{GREEN}"/>'
                f'<circle cx="calc(100% - 6px)" cy="{ROW_H//2}" r="3" fill="{GREEN}"/>'
                f'</svg>')
    return (f'<svg width="100%" height="{ROW_H}" aria-label="not connected">'
            f'<line x1="0" y1="{ROW_H//2}" x2="100%" y2="{ROW_H//2}" '
            f'stroke="{RED}" stroke-width="2" stroke-dasharray="6,5"/>'
            f'<circle cx="6" cy="{ROW_H//2}" r="3" fill="none" stroke="{RED}" '
            f'stroke-width="2"/></svg>')


def guide() -> None:
    with ui.expansion("How this works — read me first", icon="school") \
            .classes("w-full").props("dense"):
        ui.markdown(
            "**The question.** For one harness family: which circuits and "
            "connectors does the DTx put on it, under which sales-code "
            "conditions, and which of that harness's part numbers actually "
            "carry each one?\n\n"
            "**Mapping first.** A DTx family is analyzed only once it is "
            "connected to at least one complexity file — a **green solid "
            "line**. A **red dotted line** means nothing is connected and that "
            "family is skipped. Add harnesses from the dropdown (files with "
            "**no likely family** are listed first, since nothing else will "
            "surface them) or click a suggestion on the right; ✕ removes one. "
            "A family mapped to several harnesses is resolved against each "
            "separately, so you can see a circuit that is fine on one and "
            "never built on another.\n\n"
            "**Review filters** combine: *Findings*, *Needs review* (a finding "
            "or a circuit resting on an untracked code), any verdict, and a "
            "single condition — useful for seeing every circuit that shares "
            "one sales-code expression. Tick a row to add it to the "
            "**Complexity Cleanup Notes** column of the exported workbook.\n\n"
            "**Verdicts.** *unconditional* — no sales code, every build has "
            "it. *all builds* — conditioned but true for every build. "
            "*variant* — some part numbers only. **never built** — the "
            "condition holds for no build of this harness: either the circuit "
            "does not belong here, or a part number is missing a code.\n\n"
            "**Sales-code gaps.** A code the DTx conditions on that the "
            "complexity file does not track is *unknown, not absent*, so it is "
            "read as present. That can only make a circuit look wider, never "
            "invent a missing one — but every circuit resting on such a code "
            "is reading wider than the data can justify, which is what the "
            "Sales-code gaps tab lists."
        ).classes("text-sm")


def filter_chip(label: str, active: bool, on_click, count: int) -> None:
    """A filter is a real button (keyboard-operable, pressed state)."""
    c.toggle_chip(label, active, on_click, count)
