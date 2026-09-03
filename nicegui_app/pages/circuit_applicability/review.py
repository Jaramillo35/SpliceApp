"""Card 4 — the review: circuits, connectors and gaps per family, ticked for cleanup."""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme
from nicegui_app.pages.circuit_applicability.common import (
    GREEN_TEXT, RED_TEXT, VERDICT_KIND, filter_chip,
)
from nicegui_app.pages.circuit_applicability.workbench import Workbench
from splice.dtxcircuits import report as report_mod


def build(wb: Workbench) -> None:
    state = wb.state

    def _passes(analysis, item, kind: str) -> bool:
        """Whether one row survives the active filters (they combine)."""
        f = state["filters"]
        if f["findings"] and not item.is_finding:
            return False
        if f["needs_review"] and not (
                item.is_finding or item.relies_on_untracked):
            return False
        if f["verdicts"] and item.classification not in f["verdicts"]:
            return False
        if f["condition"] is not None and \
                (item.expression or "") != f["condition"]:
            return False
        return True

    def _clear_filters() -> None:
        state["filters"] = {"findings": False, "needs_review": False,
                            "verdicts": set(), "condition": None}
        results_view.refresh()

    def _toggle_flag(name: str) -> None:
        state["filters"][name] = not state["filters"][name]
        results_view.refresh()

    def _toggle_verdict(verdict: str) -> None:
        verdicts = state["filters"]["verdicts"]
        verdicts.symmetric_difference_update({verdict})
        results_view.refresh()

    def _set_condition(value) -> None:
        state["filters"]["condition"] = value or None
        results_view.refresh()

    @ui.refreshable
    def results_view() -> None:
        entries = state["entries"]
        if not entries:
            return
        labels = [e.label for e in entries]
        if state["selected"] not in labels:
            state["selected"] = labels[0]
        entry = next(e for e in entries if e.label == state["selected"])

        with c.section("4 · Review", step="Review"):
            _cleanup_bar()
            with ui.row().classes("w-full gap-4 items-start no-wrap"):
                with ui.column().classes("gap-1 min-w-[15rem]"):
                    ui.label("Family × harness").classes("sx-eyebrow")
                    for e in entries:
                        _master_row(e)
                with ui.column().classes("flex-1 min-w-0 gap-2"):
                    _detail(entry)

    def _master_row(entry) -> None:
        a = entry.analysis
        n_find = len(a.findings) + len(a.cnum_findings)
        active = entry.label == state["selected"]
        row = ui.button(on_click=lambda _e, lbl=entry.label: (
            state.update(selected=lbl), results_view.refresh())) \
            .props(f'flat no-caps align=left aria-pressed="{"true" if active else "false"}"') \
            .classes("rounded px-2 py-1.5 w-full normal-case") \
            .style(f"background:{theme.wash(theme.BRAND)}" if active
                   else f"background:{theme.SURFACE_2}")
        with row:
            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                ui.icon("report" if n_find else "check_circle") \
                    .classes("text-sm") \
                    .style(f"color:{RED_TEXT if n_find else GREEN_TEXT}")
                with ui.column().classes("gap-0 min-w-0 items-start"):
                    ui.label(entry.family).classes(
                        "text-xs font-semibold truncate")
                    ui.label(f"{a.harness} · {len(a.circuits)} ckt"
                             + (f" · {n_find} finding(s)" if n_find else "")) \
                        .classes("text-xs sx-muted truncate")

    def _cleanup_bar() -> None:
        """What is selected for cleanup, and the export that carries it."""
        selected = state["cleanup"]
        live = {report_mod.item_key(e.family, e.analysis.harness, k, i)
                for e in state["entries"]
                for k, ids in (
                    ("circuit", [x.circuit for x in e.analysis.circuits]),
                    ("connector", [x.cnum for x in e.analysis.cnums]),
                    ("gap", [g.code for g in e.analysis.code_gaps]))
                for i in ids}
        here = sum(1 for k in selected if k in live)
        with ui.row().classes("items-center gap-2 flex-wrap w-full"):
            c.chip("info" if selected else "ok",
                   f"{len(selected)} row(s) selected for "
                   f"{report_mod.CLEANUP_COLUMN}"
                   + (f" · {len(selected) - here} from another run"
                      if len(selected) > here else ""))
            if selected:
                ui.button("Clear selection", icon="clear_all",
                          on_click=lambda: (state["cleanup"].clear(),
                                            wb.persist(),
                                            results_view.refresh())) \
                    .props("flat dense size=sm")
            ui.space()
            name = c.export_name("Circuit_Applicability_Review")
            ui.button(name, icon="download",
                      on_click=lambda n=name: _export(n)).props("outline dense no-caps")
        if state["auto_added"]:
            c.note("info", f"{state['auto_added']} finding(s) were added to the "
                           "review by the last run — untick any you do not want "
                           "the customer to see")

    async def _export(name: str) -> None:
        # Off the event loop. A real programme is ~5,400 circuit ends, and
        # building the workbook inline blocks the websocket long enough
        # that the browser reports a lost connection and reconnects —
        # which reads to the user as the app restarting.
        context = {i.expression: {"kind": i.kind, "rows": i.rows,
                                  "families": i.families, "circuits": i.circuits}
                   for i in state["issues"]}
        meta = state["dtx_meta"]
        data = await c.run_engine(
            report_mod.build_report,
            list(state["entries"]), dict(state["cleanup"]),
            running="Building the review workbook…", done="Review ready",
            dtx_program=meta.program if meta else "",
            dtx_phase=meta.phase if meta else "",
            repairs=dict(state["fixes"]), repair_context=context,
            quality=state["quality"], charts=list(state["charts"]))
        if data is not None:
            c.deliver(data, name)

    def _toggle_cleanup(entry, kind: str, ident: str) -> None:
        key = report_mod.item_key(entry.family, entry.analysis.harness,
                                  kind, ident)
        if key in state["cleanup"]:
            del state["cleanup"][key]
            state["dismissed"].add(key)
        else:
            state["dismissed"].discard(key)
            selection = report_mod.selection_for(entry, kind, ident)
            if selection:
                state["cleanup"][key] = selection
        wb.persist()
        results_view.refresh()

    def _is_selected(entry, kind: str, ident: str) -> bool:
        return report_mod.item_key(entry.family, entry.analysis.harness,
                                   kind, ident) in state["cleanup"]

    def _detail(entry) -> None:
        a = entry.analysis
        with ui.row().classes("gap-2 flex-wrap"):
            c.chip("info", f"{entry.family} → {a.harness} · def "
                           f"{a.def_id or '—'} · {a.builds} build(s)")
            for label, n in a.counts.items():
                if n:
                    c.chip(VERDICT_KIND.get(label, "info"), f"{n} {label}")
        _filter_bar(a)
        # Tabs are named, and the active one is remembered: ticking a row
        # refreshes this whole card, and an unnamed tab set would snap back
        # to Circuits every time — losing your place mid-review.
        with ui.tabs(value=state["tab"],
                     on_change=lambda e: state.update(tab=e.value)) \
                .props("dense align=left") as tabs:
            ui.tab("circuits", label=f"Circuits ({len(a.circuits)})")
            ui.tab("connectors", label=f"Connectors ({len(a.cnums)})")
            ui.tab("gaps", label=f"Sales-code gaps ({len(a.code_gaps)})")
        with ui.tab_panels(tabs, value=state["tab"]).classes("w-full"):
            with ui.tab_panel("circuits").classes("p-0 pt-2"):
                _circuit_table(entry)
            with ui.tab_panel("connectors").classes("p-0 pt-2"):
                _cnum_table(entry)
            with ui.tab_panel("gaps").classes("p-0 pt-2"):
                _gap_view(entry)

    def _filter_bar(a) -> None:
        f = state["filters"]
        conditions = sorted({c.expression or "" for c in a.circuits
                             if c.expression})
        with ui.row().classes("items-center gap-2 flex-wrap mt-1"):
            ui.label("Filter").classes("sx-eyebrow")
            filter_chip("Findings", f["findings"],
                        lambda: _toggle_flag("findings"),
                        len([x for x in a.circuits if x.is_finding]))
            filter_chip("Needs review", f["needs_review"],
                        lambda: _toggle_flag("needs_review"),
                        len([x for x in a.circuits
                             if x.is_finding or x.relies_on_untracked]))
            for verdict, n in a.counts.items():
                if n:
                    filter_chip(verdict, verdict in f["verdicts"],
                                lambda v=verdict: _toggle_verdict(v), n)
            ui.select({None: "any condition",
                       **{x: x for x in conditions}},
                      value=f["condition"], label="Condition",
                      on_change=lambda e: _set_condition(e.value)) \
                .props("dense outlined options-dense").classes(
                    "text-xs min-w-[12rem]")
            if f["findings"] or f["needs_review"] or f["verdicts"] \
                    or f["condition"]:
                ui.button("Clear", icon="filter_alt_off",
                          on_click=_clear_filters).props("flat dense size=sm")

    def _circuit_table(entry) -> None:
        a = entry.analysis
        shown = [x for x in a.circuits if _passes(a, x, "circuit")]
        ui.label(f"{len(shown)} of {len(a.circuits)} circuit(s) shown · tick "
                 f"a row to add it to {report_mod.CLEANUP_COLUMN}") \
            .classes("text-xs sx-muted")
        if not shown:
            c.empty("No circuit matches these filters.", icon="filter_alt")
            return
        for x in sorted(shown, key=lambda x: (not x.is_finding, x.circuit)):
            _row(entry, "circuit", x.circuit, x.classification,
                 x.expression or "(none)",
                 f"{len(x.builds_with)}/{x.build_count}"
                 if x.build_count else "—",
                 ", ".join(x.builds_with[:4]),
                 ", ".join(x.untracked_codes), x.is_finding)

    def _cnum_table(entry) -> None:
        a = entry.analysis
        shown = [x for x in a.cnums if _passes(a, x, "connector")]
        ui.label(f"{len(shown)} of {len(a.cnums)} connector(s) shown") \
            .classes("text-xs sx-muted")
        if not shown:
            c.empty("No connector matches these filters.", icon="filter_alt")
            return
        for x in sorted(shown, key=lambda x: (not x.is_finding, x.cnum)):
            _row(entry, "connector", x.cnum, x.classification,
                 x.expression or "(none)",
                 f"{len(x.builds_with)}/{x.build_count}"
                 if x.build_count else "—",
                 f"{len(x.circuits)} ckt: " + ", ".join(x.circuits[:4]),
                 ", ".join(x.untracked_codes), x.is_finding)

    def _row(entry, kind: str, ident: str, verdict: str, condition: str,
             builds: str, carried: str, untracked: str,
             finding: bool) -> None:
        selected = _is_selected(entry, kind, ident)
        with ui.row().classes(
                "items-center gap-2 w-full no-wrap rounded px-2 py-1") \
                .style(f"background:{theme.wash(theme.BRAND)}" if selected
                       else f"background:{theme.SURFACE_2}"):
            ui.checkbox(value=selected,
                        on_change=lambda _e, k=kind, i=ident:
                            _toggle_cleanup(entry, k, i)) \
                .props(f'dense size=xs aria-label="Select {ident} for cleanup"')
            ui.label(ident).classes("text-xs font-semibold w-24 shrink-0")
            c.chip(VERDICT_KIND.get(verdict, "info"), verdict)
            ui.label(condition).classes("text-xs sx-mono w-40 truncate")
            ui.label(builds).classes("text-xs sx-muted w-14 shrink-0")
            ui.label(carried).classes("text-xs sx-muted truncate flex-1")
            if untracked:
                c.chip("review", f"untracked: {untracked}")

    def _gap_view(entry) -> None:
        a = entry.analysis
        ui.label("Sales codes the DTx conditions on for this family that its "
                 "complexity file does not track. They are read as PRESENT, "
                 "so every circuit below applies more widely than the data "
                 "can justify.").classes("text-xs sx-muted")
        if not a.code_gaps:
            c.chip("ok", "Every code the DTx uses here is tracked")
        for g in a.code_gaps:
            selected = _is_selected(entry, "gap", g.code)
            with ui.row().classes(
                    "items-center gap-2 w-full no-wrap rounded px-2 py-1") \
                    .style(f"background:{theme.wash(theme.BRAND)}" if selected
                           else f"background:{theme.SURFACE_2}"):
                ui.checkbox(value=selected,
                            on_change=lambda _e, code=g.code:
                                _toggle_cleanup(entry, "gap", code)) \
                    .props(f'dense size=xs aria-label="Select gap {g.code} for cleanup"')
                ui.label(g.code).classes("text-xs font-semibold w-20")
                ui.label(f"{g.occurrences} DTx row(s)") \
                    .classes("text-xs sx-muted w-28")
                ui.label("circuits: " + ", ".join(g.circuits[:8])) \
                    .classes("text-xs sx-muted truncate flex-1")
        if a.unused_codes:
            ui.label("Tracked by the complexity file but never conditioned "
                     "on by a DTx circuit in this family:").classes(
                "text-xs sx-muted mt-2")
            ui.label(", ".join(a.unused_codes)).classes("text-xs sx-mono")

    wb.views["results"] = results_view
    results_view()
