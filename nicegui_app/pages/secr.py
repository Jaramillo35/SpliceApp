"""SECR Database — NiceGUI page (Archetype C, Records).

A record page is searched: the Browse tab opens on the search row and the
results sit under it, capped and saying so. The DTCR report library has its
own tab; the Dashboard keeps the chart and the counts the same query already
knows. Every tab is deep-linkable — ``/secr?tab=library``.
"""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from secrdb.core.secr import api
from secrdb.core.secr.importer import import_secr_files

TABS = ("browse", "create", "update", "import", "dashboard", "library")

#: the columns the browser's query returns, in the order the table shows them
BROWSE_COLUMNS = ["secr_number", "version", "program", "model_year", "phase",
                  "harness_family", "change_type", "change_count", "match_reason"]
BROWSE_LABELS = {
    "secr_number": "SECR #",
    "version": "Version",
    "program": "Program",
    "model_year": "Model year",
    "phase": "Phase",
    "harness_family": "Harness family",
    "change_type": "Change type",
    "change_count": "Changes",
    "match_reason": "Matched on",
}
#: rows shown; the query fetches more so the table can say what it cut
SHOW_CAP = 200
FETCH_LIMIT = 1000
#: the Dashboard's one query — a header per SECR version, not the change rows
DASHBOARD_LIMIT = 5000
MAX_ERROR_LINES = 10


@ui.page("/secr")
def page(tab: str = "browse") -> None:
    opened = tab if tab in TABS else "browse"
    with c.frame("SECR Database",
                 "Every SECR generated or imported, searchable by SECR #, "
                 "DTCR, CNUM, circuit, connector, program, or harness family."):
        from nicegui_app.pages import secr_forms

        with ui.tabs().props("dense align=left") as tabs:
            ui.tab("browse", label="Browse")
            ui.tab("create", label="Create SECR")
            ui.tab("update", label="Update SECR")
            ui.tab("import", label="Import SECR files")
            ui.tab("dashboard", label="Dashboard")
            ui.tab("library", label="DTCR library")
        with ui.tab_panels(tabs, value=opened).classes("w-full"):
            with ui.tab_panel("browse").classes("p-0 pt-3"):
                _browse()
            with ui.tab_panel("create").classes("p-0 pt-3"):
                secr_forms.create_tab()
            with ui.tab_panel("update").classes("p-0 pt-3"):
                secr_forms.update_tab()
            with ui.tab_panel("import").classes("p-0 pt-3"):
                _import_tab()
            with ui.tab_panel("dashboard").classes("p-0 pt-3"):
                _dashboard()
            with ui.tab_panel("library").classes("p-0 pt-3"):
                secr_forms.library_panel()


# ---------------------------------------------------------------- browse
def _browse() -> None:
    with c.card("Browse", "A SECR number, subject, DTCR or bulletin — or any "
                          "CNUM, circuit or connector part number a change "
                          "touched. A prefix matches too: A937 also finds A937F."):
        results = None   # bound below; the search row is built first

        def refresh() -> None:
            results.clear()
            with results:
                try:
                    rows = api.search_secrs(query.value or "", limit=FETCH_LIMIT)
                except Exception as exc:  # noqa: BLE001 — the DB may be absent or locked; the tab says so
                    c.note("blocker", f"Search failed: {exc}")
                    return
                if not rows:
                    c.empty("No SECRs match — clear the search, or import "
                            "SECR files in the Import tab.", icon="search_off")
                    return
                view = [{k: str(r.get(k, "") or "") for k in BROWSE_COLUMNS}
                        for r in rows]
                c.frame_table(view, columns=BROWSE_COLUMNS, labels=BROWSE_LABELS,
                              cap=SHOW_CAP, mono=("secr_number", "match_reason"))

        with ui.row().classes("w-full items-end gap-2 no-wrap"):
            query = ui.input("Search",
                             placeholder="SECR #, DTCR, CNUM, circuit, connector "
                                         "PN, program or harness family") \
                .classes("flex-1").props("clearable dense")
            ui.button("Search", icon="search", on_click=lambda: refresh()) \
                .props("unelevated dense no-caps")
        query.on("keydown.enter", lambda: refresh())
        query.on("clear", lambda: refresh())
        results = ui.column().classes("w-full")
        refresh()


# ---------------------------------------------------------------- import
def _import_tab() -> None:
    with c.card("Import SECR workbooks",
                "Existing SECR .xlsx files are parsed and added to the database; "
                "a file already present is skipped, never overwritten."):
        pending: dict[str, bytes] = {}
        c.upload_row("SECR workbook(s) (.xlsx)",
                     lambda n, b: pending.__setitem__(n, b),
                     accept=".xlsx", multiple=True)
        report = ui.column().classes("w-full gap-1")

        async def do_import() -> None:
            def work():
                return import_secr_files(list(pending.items()))

            summary = await c.run_engine(work, running=f"Importing {len(pending)} file(s)…",
                                         done="Import finished")
            if summary is None:
                return
            pending.clear()
            c.recheck()
            report.clear()
            with report:
                _import_report(summary)

        c.action("Import", do_import, icon="upload",
                 needs=lambda: [] if pending else ["at least one SECR workbook"])


def _import_report(summary) -> None:
    """Chips for what happened, one note per file that could not be read."""
    with ui.row().classes("items-center gap-2 flex-wrap"):
        c.chip("ok", f"{len(summary.imported)} imported")
        if summary.replaced:
            c.chip("info", f"{len(summary.replaced)} replaced")
        if summary.duplicates:
            c.chip("info", f"{len(summary.duplicates)} skipped (already present)")
        if summary.failed:
            c.chip("blocker", f"{len(summary.failed)} failed")
    for r in summary.failed[:MAX_ERROR_LINES]:
        c.note("blocker", f"{r.filename} — {r.message}")
    if len(summary.failed) > MAX_ERROR_LINES:
        c.note("blocker", f"…and {len(summary.failed) - MAX_ERROR_LINES} more")
    for r in summary.with_warnings[:MAX_ERROR_LINES]:
        c.note("high", f"{r.filename} — " + "; ".join(r.warnings))
    if len(summary.with_warnings) > MAX_ERROR_LINES:
        c.note("high", f"…and {len(summary.with_warnings) - MAX_ERROR_LINES} "
                       "more with warnings")


# ------------------------------------------------------------- dashboard
def _dashboard() -> None:
    with c.card("Most affected harness families",
                "Every SECR version in the database, counted by harness family."):
        try:
            rows = api.search_secrs("", limit=DASHBOARD_LIMIT)
        except Exception as exc:  # noqa: BLE001 — the DB may be absent or locked; the tab says so
            c.note("blocker", f"Dashboard unavailable: {exc}")
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
        secrs = len({str(r.get("secr_number") or "") for r in rows})
        changes = sum(int(r.get("change_count") or 0) for r in rows)
        with c.kpi_strip():
            c.kpi(len(counts), "Harness families")
            c.kpi(secrs, "SECRs")
            c.kpi(len(rows), "SECR versions")
            c.kpi(changes, "Change records")
        top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:12]
        c.echart({
            "grid": {"left": 140, "right": 24, "top": 8, "bottom": 24},
            "xAxis": {"type": "value"},
            "yAxis": {"type": "category",
                      "data": [name for name, _ in reversed(top)]},
            "series": [{"type": "bar",
                        "data": [n for _, n in reversed(top)],
                        "itemStyle": {"borderRadius": [0, 4, 4, 0]},
                        "barWidth": 14}],
            "tooltip": {"trigger": "axis"},
        }).classes("w-full h-80")
