"""Circuit Applicability workbench.

Three stages, in order:

1. **Load** the DTx and the individual complexity files.
2. **Map** each DTx harness family to its complexity file(s) — a family may
   take several, since one DTx family is often carried by more than one
   physical harness. Exact name matches connect themselves; the rest are added
   from the dropdown or by clicking a suggestion. The analysis runs ONLY where
   a mapping exists, because attributing one harness's builds to another
   family produces a confident wrong answer.
3. **Review** circuits, connectors (CNUM) and sales-code gaps per family.

One module per card. They share a :class:`Workbench` — the state dict and
a registry of each card's refreshable view — and nothing else. The order
below is the order on the page; the quality card is measured only once an
analysis exists, so it sits after the review.

Archetype B: a sticky step bar names every stage from the first paint and
carries its state; a KPI strip under it follows the same state; the header
says who saved the workbench last.
"""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app.pages.circuit_applicability import (
    chart, common, inputs, integrity, kpis, mapping, quality, review,
)
from nicegui_app.pages.circuit_applicability.workbench import STEPS, Workbench


@ui.page("/circuit-applicability")
def page() -> None:
    wb = Workbench()
    with c.frame("Circuit Applicability",
                 "DTx circuits × harness complexity — mapped, then resolved "
                 "per circuit and per connector."):
        wb.envelope = c.envelope("")
        c.step_bar(*STEPS)
        kpis.build(wb)
        common.guide()
        inputs.build(wb)       # 1 · Inputs
        integrity.build(wb)    # 2 · Sales-code integrity
        mapping.build(wb)      # 3 · Map families to complexity files
        review.build(wb)       # 4 · Review
        quality.build(wb)      # 5 · DTx data quality
        chart.build(wb)        # 6 · Circuit chart
        wb.sync()
