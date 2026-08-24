"""SECR Database — NiceGUI page (wave 1: Browse, Import, Dashboard).

Create/Update SECR and the DTCR report library stay on the Streamlit page
until wave 2 — they are the two large form flows.
"""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme
from secrdb.core.secr import api
from secrdb.core.secr.importer import import_secr_files

BROWSE_COLUMNS = ["secr_number", "program", "model_year", "harness_family",
                  "phase", "change_type", "match_reason"]


@ui.page("/secr")
def page() -> None:
    with c.frame("SECR Database",
                 "Every SECR generated or imported, searchable by SECR #, "
                 "DTCR, CNUM, circuit, connector, program, or harness family."):
        with ui.tabs().props("dense align=left") as tabs:
            t_browse = ui.tab("Browse")
            t_import = ui.tab("Import SECR files")
            t_dash = ui.tab("Dashboard")
        with ui.tab_panels(tabs, value=t_browse).classes("w-full"):
            with ui.tab_panel(t_browse).classes("p-0 pt-3"):
                _browse()
            with ui.tab_panel(t_import).classes("p-0 pt-3"):
                _import_tab()
            with ui.tab_panel(t_dash).classes("p-0 pt-3"):
                _dashboard()

        with c.card("Create / Update SECR"):
            ui.label("The Create, Update, and DTCR-report flows migrate in the "
                     "next wave — meanwhile they live on the Streamlit page.") \
                .classes("text-sm sx-muted")


def _browse() -> None:
    with c.card("Search", "D2784J, A937F, 50319, D50319A, IP …"):
        query = ui.input(placeholder="Search every change in the database") \
            .classes("w-full").props("clearable dense")
        table_holder = ui.column().classes("w-full")

        def refresh() -> None:
            table_holder.clear()
            try:
                rows = api.search_secrs(query.value or "", limit=200)
            except Exception as exc:
                with table_holder:
                    ui.label(f"Search failed: {exc}") \
                        .style(f"color:{theme.STATUS['blocker']}")
                return
            with table_holder:
                if not rows:
                    c.empty("No SECRs match — clear the search, or import "
                            "SECR files in the Import tab.", icon="search_off")
                    return
                view = [{k: str(r.get(k, "")) for k in BROWSE_COLUMNS} for r in rows]
                ui.table(rows=view, columns=[
                    {"name": k, "label": k.replace("_", " ").title(),
                     "field": k, "align": "left", "sortable": True}
                    for k in BROWSE_COLUMNS],
                    pagination=25).classes("w-full").props("dense flat")

        query.on("keydown.enter", lambda: refresh())
        ui.button("Search", icon="search", on_click=refresh).props("dense outline")
        refresh()


def _import_tab() -> None:
    with c.card("Import SECR workbooks",
                "Existing SECR .xlsx files are parsed and added to the database; "
                "duplicates are skipped."):
        pending: dict[str, bytes] = {}
        c.upload_zone("SECR workbook(s) (.xlsx)",
                      lambda n, b: pending.__setitem__(n, b),
                      accept=".xlsx", multiple=True)
        report = ui.column().classes("w-full gap-1")

        async def do_import() -> None:
            if not pending:
                ui.notify("Add SECR files first", type="warning")
                return

            def work():
                return import_secr_files(list(pending.items()))

            result = await c.run_engine(work, running=f"Importing {len(pending)} file(s)…",
                                        done="Import finished")
            if result is None:
                return
            pending.clear()
            report.clear()
            with report:
                imported = getattr(result, "imported", None)
                skipped = getattr(result, "skipped", None)
                errors = getattr(result, "errors", None)
                if imported is not None:
                    c.chip("ok", f"{len(imported)} imported")
                if skipped:
                    c.chip("info", f"{len(skipped)} skipped (already present)")
                for err in (errors or [])[:10]:
                    ui.label(str(err)).classes("text-xs") \
                        .style(f"color:{theme.STATUS['blocker']}")

        ui.button("Import", icon="upload", on_click=do_import).props("unelevated")


def _dashboard() -> None:
    with c.card("Most affected harness families"):
        try:
            rows = api.search_secrs("", limit=5000)
        except Exception as exc:
            ui.label(f"Dashboard unavailable: {exc}") \
                .style(f"color:{theme.STATUS['blocker']}")
            return
        if not rows:
            c.empty("Nothing to chart yet — import SECR files first.",
                    icon="insert_chart_outlined")
            return
        counts: dict[str, int] = {}
        for r in rows:
            fam = str(r.get("harness_family") or "").strip()
            if fam:
                counts[fam] = counts.get(fam, 0) + 1
        top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:12]
        ui.echart({
            "backgroundColor": "transparent",
            "grid": {"left": 140, "right": 24, "top": 8, "bottom": 24},
            "xAxis": {"type": "value",
                      "axisLabel": {"color": "rgba(232,232,236,0.6)"},
                      "splitLine": {"lineStyle": {"color": "rgba(232,232,236,0.08)"}}},
            "yAxis": {"type": "category",
                      "data": [name for name, _ in reversed(top)],
                      "axisLabel": {"color": "rgba(232,232,236,0.8)"}},
            "series": [{"type": "bar",
                        "data": [n for _, n in reversed(top)],
                        "itemStyle": {"color": theme.CHART[0],
                                       "borderRadius": [0, 4, 4, 0]},
                        "barWidth": 14}],
            "tooltip": {"trigger": "axis"},
        }).classes("w-full h-80")
        ui.label(f"{len(rows)} change rows across {len(counts)} harness families") \
            .classes("text-xs sx-muted")
