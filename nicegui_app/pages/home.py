"""Home — dashboard with one card per workflow."""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme

TOOLS = [
    ("Splice Generation", "cable", "/splice-generation",
     "Configurations, generated connections, print matrix, and the output "
     "workbook from one Complexity + OptionPerCkt file."),
    ("DTx Compare", "difference", "/dtx-compare",
     "OLD vs NEW DTx with DTCR tagging — the WEAVE change workbook and the "
     "PreOrder list."),
    ("Harness Complexity", "table_view", "/harness-complexity",
     "Individual harness-complexity .xlsm files from the master workbook — "
     "reviewed matrix, combined-expression decisions, macros preserved."),
    ("HRN Chart Builder", "stacked_bar_chart", "/hrn-chart",
     "Batch HRN + CSV (+ CMP) conversion into chart workbooks with supplier "
     "prefixes."),
    ("VBOM Risk Matrix", "grid_on", "/vbom",
     "DoAll / BuildSpec + complexity files into the VBOM workbook bundle."),
    ("Circuit Health", "monitor_heart", "/circuit-health",
     "Missing circuits across inlines: cavity checks, option-window coverage, "
     "route gaps — with SE dispositions and sign-off."),
    ("SECR Database", "storage", "/secr",
     "A searchable history of engineering changes; import workbooks and "
     "browse every change."),
    ("Ask the Database", "forum", "/ask",
     "Plain-language questions over the SECR history, answered with evidence "
     "by the local model."),
    ("Meeting Transcripts", "graphic_eq", "/transcripts",
     "Anonymized Teams caption recording — Speaker 1..N, LLM-ready minutes."),
]


@ui.page("/")
def page() -> None:
    with c.frame("Home", "System Engineer Toolkit"):
        with ui.element("div").classes("w-full grid grid-cols-1 md:grid-cols-2 gap-4"):
            for title, icon, route, desc in TOOLS:
                with ui.link(target=route).classes("no-underline"):
                    with ui.card().classes(
                            "sx-card sx-reveal w-full h-full cursor-pointer "
                            "hover:border-orange-700 transition-colors"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon(icon).classes("text-xl") \
                                .style(f"color:{theme.BRAND}")
                            ui.label(title).classes("text-base font-bold") \
                                .style(f"color:{theme.TEXT}")
                        ui.label(desc).classes("text-sm sx-muted")
