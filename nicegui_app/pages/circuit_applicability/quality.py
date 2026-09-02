"""Card 5 — DTx data quality: what to send back to the customer."""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app.pages.circuit_applicability.workbench import Workbench

COVERAGE_LABELS = {"code": "Code", "status": "Status", "rows": "DTx rows",
                   "families": "Used by", "tracked": "Tracked by",
                   "missing": "Missing from"}


def build(wb: Workbench) -> None:
    state = wb.state

    @ui.refreshable
    def quality_view() -> None:
        q = state["quality"]
        if q is None:
            return
        with c.section("5 · DTx data quality",
                       "What this export gets right, and what needs fixing at "
                       "source. The complexity files are built from the "
                       "customer's own information, so a mismatch here is "
                       "their data disagreeing with itself — which is what "
                       "makes it fair to send back.", step="Quality"):
            with ui.row().classes("gap-2 flex-wrap items-center"):
                c.chip("info", f"{q.program or '?'} · {q.phase or '?'}"
                               + (f" · {q.report_date}" if q.report_date else ""))
                c.chip("ok" if q.clean else "blocker",
                       "No findings" if q.clean
                       else f"{q.finding_total} finding(s) for the customer")

            with c.kpi_strip():
                c.kpi(q.rows, "Rows")
                c.kpi(q.circuits, "Circuits")
                c.kpi(q.connectors, "Connectors")
                c.kpi(q.families, "Families")
                c.kpi(f"{q.conditioned_rows} ({q.conditioned_share:.0%})", "Conditioned")
                c.kpi(q.distinct_codes, "Sales codes")

            ui.label("Findings").classes("sx-eyebrow mt-2")
            with c.kpi_strip():
                c.kpi(q.malformed_expressions, "Malformed expressions",
                      "blocker" if q.malformed_expressions else "ok")
                c.kpi(q.malformed_rows, "…rows affected",
                      "review" if q.malformed_rows else "ok")
                c.kpi(q.never_built_circuits, "Never-built circuits",
                      "blocker" if q.never_built_circuits else "ok")
                c.kpi(q.never_built_connectors, "Never-built connectors",
                      "blocker" if q.never_built_connectors else "ok")
                c.kpi(len(q.codes_not_tracked_anywhere), "Codes tracked nowhere",
                      "blocker" if q.codes_not_tracked_anywhere else "ok")
                c.kpi(len(q.codes_partially_tracked), "Codes partly tracked",
                      "review" if q.codes_partially_tracked else "ok")
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
                             "where it is not.").classes("sx-caption")
                    c.frame_table([{
                        "code": x.code, "status": x.status, "rows": x.dtx_rows,
                        "families": ", ".join(x.families[:4]),
                        "tracked": ", ".join(x.tracked_by[:3]) or "—",
                        "missing": ", ".join(x.missing_from[:3]) or "—",
                    } for x in q.coverage], labels=COVERAGE_LABELS,
                        pagination=15, mono=("code",))

    wb.views["quality"] = quality_view
    # measured only once an analysis exists, so it is placed after the review
    quality_view()
