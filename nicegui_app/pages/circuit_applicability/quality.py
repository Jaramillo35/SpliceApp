"""Card 5 — DTx data quality: what to send back to the customer."""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme
from nicegui_app.pages.circuit_applicability.workbench import Workbench


def build(wb: Workbench) -> None:
    state = wb.state

    @ui.refreshable
    def quality_view() -> None:
        q = state["quality"]
        if q is None:
            return
        with c.card("5 · DTx data quality",
                    "What this export gets right, and what needs fixing at "
                    "source. The complexity files are built from the "
                    "customer's own information, so a mismatch here is "
                    "their data disagreeing with itself — which is what "
                    "makes it fair to send back."):
            with ui.row().classes("gap-2 flex-wrap items-center"):
                c.chip("info", f"{q.program or '?'} · {q.phase or '?'}"
                               + (f" · {q.report_date}" if q.report_date else ""))
                c.chip("ok" if q.clean else "blocker",
                       "No findings" if q.clean
                       else f"{q.finding_total} finding(s) for the customer")

            _metric_row([
                ("Rows", q.rows, "info"),
                ("Circuits", q.circuits, "info"),
                ("Connectors", q.connectors, "info"),
                ("Families", q.families, "info"),
                ("Conditioned", f"{q.conditioned_rows} ({q.conditioned_share:.0%})", "info"),
                ("Sales codes", q.distinct_codes, "info"),
            ])

            ui.label("FINDINGS").classes(
                "sx-eyebrow mt-2")
            _metric_row([
                ("Malformed expressions", q.malformed_expressions,
                 "blocker" if q.malformed_expressions else "ok"),
                ("…rows affected", q.malformed_rows,
                 "review" if q.malformed_rows else "ok"),
                ("Never-built circuits", q.never_built_circuits,
                 "blocker" if q.never_built_circuits else "ok"),
                ("Never-built connectors", q.never_built_connectors,
                 "blocker" if q.never_built_connectors else "ok"),
                ("Codes tracked nowhere", len(q.codes_not_tracked_anywhere),
                 "blocker" if q.codes_not_tracked_anywhere else "ok"),
                ("Codes partly tracked", len(q.codes_partially_tracked),
                 "review" if q.codes_partially_tracked else "ok"),
            ])
            if q.repaired_expressions:
                c.chip("ok", f"{q.repaired_expressions} expression(s) repaired "
                             "by you — the customer should fix them at source")
            if q.families_unmapped:
                c.chip("review", f"{len(q.families_unmapped)} family(ies) not "
                                 "assessed (no complexity mapped): "
                                 + ", ".join(q.families_unmapped[:4])
                                 + ("…" if len(q.families_unmapped) > 4 else ""))

            if q.coverage:
                with ui.expansion(f"Sales-code coverage ({len(q.coverage)} codes)") \
                        .classes("w-full").props("dense"):
                    ui.label("Where each code the DTx uses is known, and "
                             "where it is not.").classes("text-xs sx-muted")
                    ui.table(rows=[{
                        "code": x.code, "status": x.status, "rows": x.dtx_rows,
                        "families": ", ".join(x.families[:4]),
                        "tracked": ", ".join(x.tracked_by[:3]) or "—",
                        "missing": ", ".join(x.missing_from[:3]) or "—",
                    } for x in q.coverage], columns=[
                        {"name": "code", "label": "Code", "field": "code",
                         "align": "left", "sortable": True},
                        {"name": "status", "label": "Status", "field": "status",
                         "align": "left", "sortable": True},
                        {"name": "rows", "label": "DTx rows", "field": "rows",
                         "align": "center", "sortable": True},
                        {"name": "families", "label": "Used by", "field": "families",
                         "align": "left"},
                        {"name": "tracked", "label": "Tracked by", "field": "tracked",
                         "align": "left"},
                        {"name": "missing", "label": "Missing from", "field": "missing",
                         "align": "left"},
                    ], pagination=15).classes("w-full").props("dense flat")

    def _metric_row(metrics) -> None:
        with ui.row().classes("gap-2 flex-wrap mt-1"):
            for label, value, kind in metrics:
                colour = theme.STATUS.get(kind, theme.STATUS["info"])
                with ui.element("div").classes("rounded px-2 py-1 min-w-[7rem]") \
                        .style(f"background:{theme.SURFACE_2};"
                               f"border:1px solid {colour}55"):
                    ui.label(str(value)).classes("text-base font-bold") \
                        .style(f"color:{colour}")
                    ui.label(label).classes("text-xs sx-muted")

    wb.views["quality"] = quality_view
    # measured only once an analysis exists, so it is placed after the review
    quality_view()
