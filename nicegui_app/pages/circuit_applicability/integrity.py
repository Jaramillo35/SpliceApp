"""Card 2 — sales-code integrity: malformed expressions and their repairs."""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme
from nicegui_app.pages.circuit_applicability.common import GREEN, RED, filter_chip
from nicegui_app.pages.circuit_applicability.workbench import Workbench
from splice.dtxcircuits import integrity


def build(wb: Workbench) -> None:
    state = wb.state

    def _resolve(expression: str, replacement: str) -> None:
        state["fixes"][expression] = replacement
        state["entries"] = state["charts"] = []   # the analysis is now stale
        wb.persist()
        wb.measure()
        wb.refresh("chart")
        integrity_view.refresh()
        wb.refresh("results")

    def _resolve_manual(expression: str, typed: str) -> None:
        """A hand-typed repair is checked before it is stored: an unchecked
        one can be malformed in its own right, and would then be applied to
        every circuit using that expression."""
        blocking, warnings = integrity.validate_replacement(expression, typed)
        if blocking:
            ui.notify(" ".join(blocking), type="negative", multi_line=True,
                      close_button=True)
            return
        for warning in warnings:
            ui.notify(warning, type="warning", multi_line=True,
                      close_button=True)
        _resolve(expression, typed.strip())

    def _unresolve(expression: str) -> None:
        state["fixes"].pop(expression, None)
        state["entries"] = state["charts"] = []
        wb.persist()
        wb.measure()
        wb.refresh("chart")
        integrity_view.refresh()
        wb.refresh("results")

    @ui.refreshable
    def integrity_view() -> None:
        if not state["issues"]:
            if state["rows"]:
                with c.card("2 · Sales-code integrity"):
                    c.chip("ok", "Every sales-code expression in this DTx "
                                 "parses — nothing to fix")
            return
        f = state["issue_filter"]
        issues = state["issues"]
        open_issues = wb.open_issues()
        kinds = sorted({i.kind for i in issues})
        shown = [i for i in issues
                 if not (f["unresolved_only"] and i.expression in state["fixes"])
                 and (not f["kinds"] or i.kind in f["kinds"])]

        with c.card("2 · Sales-code integrity",
                    "Checked before anything is resolved: a malformed "
                    "expression is false for every configuration, so its "
                    "circuits would read as 'never built' and look like "
                    "real defects."):
            with ui.row().classes("items-center gap-2 flex-wrap"):
                c.chip("blocker" if open_issues else "ok",
                       f"{len(open_issues)} unresolved")
                if len(issues) - len(open_issues):
                    c.chip("ok", f"{len(issues) - len(open_issues)} resolved "
                                 "(untick 'Unresolved only' to review)")
                ui.label("FILTER").classes(
                    "sx-eyebrow ml-2")
                filter_chip("Unresolved only", f["unresolved_only"],
                            lambda: (f.__setitem__("unresolved_only",
                                                   not f["unresolved_only"]),
                                     integrity_view.refresh()),
                            len(open_issues))
                for kind in kinds:
                    filter_chip(kind, kind in f["kinds"],
                                lambda k=kind: (
                                    f["kinds"].symmetric_difference_update({k}),
                                    integrity_view.refresh()),
                                sum(1 for i in issues if i.kind == kind))
            for issue in shown:
                _issue_row(issue)
            if not shown:
                c.empty("Nothing matches these filters.", icon="filter_alt")

    def _issue_row(issue) -> None:
        fixed = state["fixes"].get(issue.expression)
        with ui.element("div").classes("w-full rounded p-2 mt-1") \
                .style(f"background:{theme.SURFACE_2};border:1px solid "
                       f"{(GREEN if fixed else RED)}55"):
            with ui.row().classes("items-center gap-2 flex-wrap"):
                c.chip("ok" if fixed else "blocker", issue.kind)
                ui.label(issue.expression).classes(
                    "text-xs sx-mono font-semibold")
                if fixed:
                    ui.icon("arrow_forward").classes("text-xs")
                    ui.label(fixed).classes("text-xs sx-mono font-semibold") \
                        .style(f"color:{GREEN}")
                ui.label(f"{issue.rows} DTx row(s) · "
                         f"{len(issue.circuits)} circuit(s) · "
                         + ", ".join(issue.families[:3])) \
                    .classes("text-xs sx-muted")
            ui.label(issue.detail).classes("text-xs sx-muted")
            if fixed:
                with ui.row().classes("gap-2 items-center"):
                    ui.button("Undo", icon="undo",
                              on_click=lambda e=issue.expression: _unresolve(e)) \
                        .props("flat dense size=sm")
                return
            with ui.row().classes("gap-2 items-center flex-wrap mt-1"):
                for suggestion in issue.suggestions:
                    ui.button(suggestion.expression,
                              icon="auto_fix_high",
                              on_click=lambda e=issue.expression,
                                              r=suggestion.expression:
                                  _resolve(e, r)) \
                        .props("outline dense no-caps") \
                        .tooltip(suggestion.reason)
                manual = ui.input(placeholder="or type the correct expression") \
                    .props("dense outlined").classes("text-xs min-w-[14rem]")
                ui.button("Use", icon="check",
                          on_click=lambda e=issue.expression, m=manual:
                              _resolve_manual(e, m.value or "")) \
                    .props("flat dense size=sm")
            if not issue.suggestions:
                ui.label("No automatic suggestion — this one needs a human "
                         "reading.").classes("text-xs sx-muted")

    wb.views["integrity"] = integrity_view
    integrity_view()
