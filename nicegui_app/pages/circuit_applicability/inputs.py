"""Card 1 — the two upload zones, the Load button, and the progress bar."""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app.pages.circuit_applicability import actions
from nicegui_app.pages.circuit_applicability.workbench import Workbench


def build(wb: Workbench) -> None:
    state = wb.state
    with c.card("1 · Inputs",
                "Programme and phase are read from inside both file types "
                "— the DTx title block and each complexity file's Harness "
                "PN sheet — never from the filenames."):
        with ui.row().classes("w-full gap-4 flex-wrap"):
            c.upload_zone("Detailed DTx Circuits Report",
                          lambda n, b: state.update(dtx=(n, b)),
                          accept=".xls,.xlsx,.xlsm")
            c.upload_zone("Individual harness complexity file(s)",
                          lambda n, b: state["uploads"].__setitem__(n, b),
                          accept=".xlsm,.xlsx", multiple=True)
        ui.button("Load and match", icon="link",
                  on_click=lambda: actions.load(wb)).props("unelevated")
        wb.progress = ui.column().classes("w-full gap-1")
