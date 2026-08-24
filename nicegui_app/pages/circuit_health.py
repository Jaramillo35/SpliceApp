"""Circuit Health Check — NiceGUI page over splice.inline.health.

Absorbs Inline Continuity: layer 1 of the health engine IS the continuity
study, so this page is the single home for inline validation.
"""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from splice.config import DATA_DIR
from splice.inline import health
from splice.inline.complexity import read_complexity
from splice.inline.pairing import resolve
from splice.inline.summary import read_circuit_summary

BASELINE_PATH = DATA_DIR / "inline_health" / "baseline.json"
SEV_KIND = {"Blocker": "blocker", "High": "high", "Review": "review"}
KIND_LABEL = {"cavity": "Cavity mismatch", "one_sided_window": "Missing variant window",
              "route_window_gap": "Route gap"}


@ui.page("/circuit-health")
def page() -> None:
    state: dict = {"summary": None, "cx": {}, "result": None, "rejected": []}

    with c.frame("Circuit Health",
                 "Missing circuits across inlines: cavity mismatches, option "
                 "windows with builds but no wire, route gaps. Provable "
                 "variants auto-clear; the rest queues for disposition."):

        @ui.refreshable
        def metrics() -> None:
            r = state["result"]
            if not r:
                return
            baseline = health.load_baseline(BASELINE_PATH)
            open_f = r.open_findings(baseline)
            cells = [
                ("Blockers open", sum(1 for f in open_f if f.severity == "Blocker"), "blocker"),
                ("High open", sum(1 for f in open_f if f.severity == "High"), "high"),
                ("Dispositioned", len(r.findings) - len(open_f), "info"),
                ("Auto-cleared", len(r.cleared), "ok"),
            ]
            with ui.row().classes("gap-4 flex-wrap"):
                for label, value, kind in cells:
                    with ui.card().classes("sx-card px-4 py-2 items-center gap-0"):
                        ui.label(str(value)).classes("text-2xl font-bold leading-none") \
                            .style(f"color:{c.theme.STATUS[kind]}")
                        ui.label(label).classes("text-[11px] sx-muted")

        metrics()

        with c.card("Inputs", "Circuit Summary + one Harness Complexity per "
                              "harness — matched by the DEF id inside each file."):
            with ui.row().classes("w-full gap-4 flex-wrap"):
                c.upload_zone("Circuit Summary (.xlsx)",
                              lambda n, b: state.update(summary=(n, b)),
                              accept=".xlsx")
                c.upload_zone("Complexity files (.xlsm)",
                              lambda n, b: state["cx"].__setitem__(n, b),
                              accept=".xlsm,.xlsx", multiple=True)
            ui.button("Run health check", icon="play_arrow",
                      on_click=lambda: run_check()).props("unelevated")

        @ui.refreshable
        def results() -> None:
            r = state["result"]
            if not r:
                return
            baseline = health.load_baseline(BASELINE_PATH)
            dispositions = baseline.get("dispositions", {})

            with c.card("Gate 0 — input health"):
                for issue in state["rejected"]:
                    ui.label(f"✗ {issue}").classes("text-sm") \
                        .style(f"color:{c.theme.STATUS['blocker']}")
                if r.inputs.missing_complexity:
                    ui.label("Missing complexity: " + ", ".join(r.inputs.missing_complexity)) \
                        .classes("text-sm").style(f"color:{c.theme.STATUS['high']}")
                if r.inputs.skew_days > 30:
                    ui.label(f"Revision skew {r.inputs.skew_days} days — "
                             f"{r.inputs.skew_pair}") \
                        .classes("text-sm").style(f"color:{c.theme.STATUS['high']}")
                rows = [row.__dict__ for row in r.inputs.rows]
                if rows:
                    ui.table(rows=rows, columns=[
                        {"name": k, "label": k.replace("_", " ").title(),
                         "field": k, "align": "left"} for k in rows[0]]) \
                        .classes("w-full").props("dense flat")

            open_f = r.open_findings(baseline)
            done_f = [f for f in r.findings if f not in open_f]

            with c.card():
                with ui.tabs().props("dense align=left") as tabs:
                    t_open = ui.tab(f"Open ({len(open_f)})")
                    t_done = ui.tab(f"Dispositioned ({len(done_f)})")
                    t_clear = ui.tab(f"Auto-cleared ({len(r.cleared)})")
                    t_audit = ui.tab("Continuity audit")
                with ui.tab_panels(tabs, value=t_open).classes("w-full"):
                    with ui.tab_panel(t_open).classes("p-0 pt-2"):
                        if not open_f:
                            c.chip("ok", "Nothing open")
                        for f in open_f:
                            finding_row(f, dispositions)
                    with ui.tab_panel(t_done).classes("p-0 pt-2"):
                        for f in done_f:
                            finding_row(f, dispositions)
                    with ui.tab_panel(t_clear).classes("p-0 pt-2"):
                        for p in r.cleared[:300]:
                            ui.label(f"{p.inline} · cav {p.cavity} · {p.window}") \
                                .classes("text-xs sx-mono sx-muted")
                    with ui.tab_panel(t_audit).classes("p-0 pt-2"):
                        _audit_tab(r)

            with c.card("Sign-off & report"):
                engineer = ui.input("Systems Engineer").classes("w-60")
                blocking = r.blocking_open(baseline)
                with ui.row().classes("gap-2 items-center"):
                    ui.button("Sign off this run", icon="task_alt",
                              on_click=lambda: do_signoff(engineer.value)) \
                        .props("unelevated").set_enabled(not blocking)
                    if blocking:
                        c.chip("high", f"{len(blocking)} open Blocker/High must be "
                                       "dispositioned first")
                    c.download_button("Circuit_Health_Report.xlsx",
                                      lambda: health.render_report(
                                          state["result"],
                                          health.load_baseline(BASELINE_PATH)))

        def _audit_tab(r) -> None:
            """The former Inline Continuity page, in full: every cavity,
            marked differences, readiness gaps, and the findings workbook."""
            from splice.inline import report as inline_report
            study = r.study
            if study is None:
                c.empty("Run the health check to build the audit.")
                return
            counts = study.verdict_counts()
            with ui.row().classes("gap-6 py-1"):
                for label, value in [
                        ("Cavities checked", f"{study.cavities_checked:,}"),
                        ("Continuous", f"{counts.get('Continuous', 0):,}"),
                        ("Need review", f"{len(study.review):,}"),
                        ("Inline pairs", f"{len(study.pairs):,}")]:
                    with ui.column().classes("items-center gap-0"):
                        ui.label(value).classes("text-xl font-bold")
                        ui.label(label).classes("text-[11px] sx-muted")
            if r.gaps:
                with ui.expansion(f"Input readiness notes ({len(r.gaps)})") \
                        .classes("w-full").props("dense"):
                    _frame_table(inline_report.gaps_frame(r.gaps))
            for title, frame in [
                    ("Cavities needing review", inline_report.review_frame(study)),
                    ("Marked differences inside continuous cavities",
                     inline_report.marked_frame(study)),
                    ("Every cavity", inline_report.all_frame(study)),
                    ("Every circuit (one row per wire)",
                     inline_report.options_frame(study))]:
                with ui.expansion(f"{title} ({len(frame)})").classes("w-full") \
                        .props("dense"):
                    _frame_table(frame)
            c.download_button(
                "Inline_Continuity_Findings.xlsx",
                lambda: inline_report.build_workbook(state["result"].study,
                                                     state["result"].gaps))

        def _frame_table(df, limit: int = 500) -> None:
            if df is None or df.empty:
                ui.label("None.").classes("text-sm sx-muted")
                return
            view = df.head(limit).astype(str)
            ui.table(rows=view.to_dict("records"), columns=[
                {"name": col, "label": col, "field": col, "align": "left"}
                for col in view.columns], pagination=25) \
                .classes("w-full").props("dense flat")

        def finding_row(f, dispositions) -> None:
            d = dispositions.get(f.fingerprint)
            with ui.expansion().classes("w-full").props("dense") as exp:
                with exp.add_slot("header"):
                    with ui.row().classes("items-center gap-3 w-full py-1 flex-wrap"):
                        c.chip(SEV_KIND.get(f.severity, "info"), f.severity)
                        ui.label(KIND_LABEL.get(f.kind, f.kind)) \
                            .classes("text-sm font-semibold")
                        ui.label(f.inline + (f" · cav {f.cavity}" if f.cavity else "")
                                 + (f" · {f.circuit}" if f.circuit else "")) \
                            .classes("text-sm sx-muted")
                        if f.kind == "one_sided_window":
                            ui.label(f"{f.harness_with} → missing on {f.harness_without}") \
                                .classes("text-xs sx-muted")
                        if d:
                            ui.icon("verified").style(f"color:{c.theme.STATUS['ok']}")
                ui.label(f.detail).classes("text-sm")
                if f.window:
                    ui.label(f.window).classes("text-xs sx-mono p-2 rounded w-full") \
                        .style(f"background:{c.theme.CANVAS}")
                if f.builds_without:
                    ui.label("Builds without the wire: " + ", ".join(f.builds_without)) \
                        .classes("text-xs").style(f"color:{c.theme.STATUS['blocker']}")
                if d:
                    ui.label(f"{d['verdict']} — {d.get('reason', '')} "
                             f"({d.get('by', '')}, {d.get('date', '')})") \
                        .classes("text-xs").style(f"color:{c.theme.STATUS['ok']}")
                else:
                    ui.button("Disposition…", icon="gavel",
                              on_click=lambda f=f: disposition_dialog(f)) \
                        .props("outline dense")

        def disposition_dialog(f) -> None:
            with ui.dialog() as dialog, ui.card().classes("w-96 sx-card"):
                ui.label("Disposition finding").classes("text-base font-bold")
                ui.label(f"{f.inline} · {f.circuit}").classes("text-sm sx-muted")
                verdict = ui.select(list(health.DISPOSITIONS),
                                    value=health.DISPOSITIONS[0],
                                    label="Verdict").classes("w-full")
                reason = ui.input("Reason").classes("w-full")
                who = ui.input("Engineer", value="SE").classes("w-full")

                def save() -> None:
                    baseline = health.load_baseline(BASELINE_PATH)
                    health.disposition(baseline, f, verdict.value,
                                       reason.value, who.value)
                    health.save_baseline(BASELINE_PATH, baseline)
                    dialog.close()
                    ui.notify(f"Recorded: {verdict.value}", type="positive")
                    results.refresh()
                    metrics.refresh()

                with ui.row().classes("justify-end w-full gap-2"):
                    ui.button("Cancel", on_click=dialog.close).props("flat")
                    ui.button("Save", on_click=save).props("unelevated")
            dialog.open()

        def do_signoff(by: str) -> None:
            baseline = health.load_baseline(BASELINE_PATH)
            health.sign_off(baseline, by or "SE")
            health.save_baseline(BASELINE_PATH, baseline)
            ui.notify("Run signed off and recorded", type="positive")

        results()

        async def run_check() -> None:
            if not (state["summary"] and state["cx"]):
                ui.notify("Load the Circuit Summary and complexity files first",
                          type="warning")
                return

            def work():
                name, blob = state["summary"]
                harnesses, ends = read_circuit_summary(blob, name)
                complexity, rejected = {}, []
                for name, blob in state["cx"].items():
                    try:
                        cx = read_complexity(blob, name)
                        cx.complexity_file = name
                        if cx.def_id in harnesses:
                            complexity[cx.def_id] = cx
                        else:
                            rejected.append(f"{name} (DEF id {cx.def_id} not in the summary)")
                    except Exception as exc:
                        rejected.append(f"{name}: {exc}")
                pairs, unmated = resolve(ends, set(harnesses))
                return health.analyze(harnesses, ends, complexity, pairs, unmated), rejected

            out = await c.run_engine(work, running="Analyzing every inline, cavity, "
                                                   "and option window…",
                                     done="Health check complete")
            if out is not None:
                state["result"], state["rejected"] = out
                metrics.refresh()
                results.refresh()
