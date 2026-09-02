"""The KPI strip under the step bar — the workbench at a glance."""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app.pages.circuit_applicability.workbench import Workbench


def build(wb: Workbench) -> None:
    state = wb.state

    @ui.refreshable
    def kpi_view() -> None:
        if not state["rows"]:
            return
        total = len(state["families"])
        connected = sum(1 for v in state["mapping"].values() if v)
        open_families = total - connected
        malformed = len(wb.open_issues())
        q = state["quality"]
        with c.kpi_strip():
            c.kpi(total, "Families")
            c.kpi(connected, "Connected", "ok" if connected else None)
            c.kpi(open_families, "Open", "blocker" if open_families else None)
            c.kpi(malformed, "Malformed", "blocker" if malformed else None)
            if q is not None:
                never = q.never_built_circuits + q.never_built_connectors
                c.kpi(never, "Never built", "blocker" if never else "ok")
            c.kpi(len(state["cleanup"]), "Selected for cleanup",
                  "info" if state["cleanup"] else None)

    wb.views["kpis"] = kpi_view
    kpi_view()
