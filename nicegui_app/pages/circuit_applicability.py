"""Circuit Applicability — which part numbers carry which circuits, per harness.

DTx (circuits and their sales codes) + one individual complexity file per
harness (the builds). The identity of both comes from inside the files — the
DTx title block and each complexity file's Harness PN sheet — and a
correspondence gate runs before any analysis, because mixing a build phase
produces a plausible, wrong answer rather than an error.
"""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme

CLASS_KIND = {
    "unconditional": "ok",
    "all builds": "ok",
    "variant": "info",
    "never built": "blocker",
    "no complexity": "review",
}


def _guide() -> None:
    with ui.expansion("How this works — read me first", icon="school") \
            .classes("w-full").props("dense"):
        ui.markdown(
            "**The question.** For one harness family: which circuits does the "
            "DTx put on it, under which sales-code conditions, and which of "
            "that harness's part numbers actually carry each circuit?\n\n"
            "**How.** Circuits are grouped per harness family and each "
            "circuit's conditions are unioned across its pins (a circuit "
            "reachable unconditionally at any pin is unconditional). That "
            "condition is then evaluated against the builds in **that "
            "harness's own** complexity file — never another's.\n\n"
            "**What each verdict means.**\n"
            "- **unconditional** — no sales code; every build carries it.\n"
            "- **all builds** — conditioned, but true for every build.\n"
            "- **variant** — carried by some part numbers and not others.\n"
            "- **never built** — the DTx puts the circuit on this harness "
            "under a condition **no build can satisfy**. Either the circuit "
            "does not belong here, or a part number is missing a code.\n"
            "- **no complexity** — no file loaded for that family; not "
            "guessed, and never reported as a finding.\n\n"
            "**Untracked codes.** A code the complexity file does not track is "
            "*unknown*, not absent, so it is treated as present. That can only "
            "widen a circuit's applicability, never invent a missing one — but "
            "a wide answer resting on silence is worth knowing, so those codes "
            "are listed per circuit and per harness."
        ).classes("text-sm")


@ui.page("/circuit-applicability")
def page() -> None:
    from splice.dtxcircuits import analyze, correspond, read_dtx_circuits
    from splice.dtxcircuits.complexity import read_harness_file

    state: dict = {"dtx": None, "complexity": {}, "result": None}

    with c.frame("Circuit Applicability",
                 "DTx circuits × harness complexity → which part numbers "
                 "carry which circuit."):
        _guide()

        with c.card("Inputs",
                    "Programme and phase are read from inside both file types "
                    "— the DTx title block and each complexity file's Harness "
                    "PN sheet — never from the filenames."):
            with ui.row().classes("w-full gap-4 flex-wrap"):
                c.upload_zone("Detailed DTx Circuits Report",
                              lambda n, b: state.update(dtx=(n, b)),
                              accept=".xls,.xlsx,.xlsm")
                c.upload_zone("Individual harness complexity file(s)",
                              lambda n, b: state["complexity"].__setitem__(n, b),
                              accept=".xlsm,.xlsx", multiple=True)
            ui.button("Analyze", icon="play_arrow",
                      on_click=lambda: run()).props("unelevated")
            progress_box = ui.column().classes("w-full gap-1")

        @ui.refreshable
        def render() -> None:
            result = state["result"]
            if not result:
                return
            dtx_meta, corr, analyses = result
            _render_gate(dtx_meta, corr)
            _render_summary(analyses)
            _render_harnesses(analyses)

        def _render_gate(dtx_meta, corr) -> None:
            with c.card("Inputs check",
                        f"DTx: {dtx_meta.program or '(no programme stated)'} · "
                        f"phase {dtx_meta.phase or '(none)'} · "
                        f"{dtx_meta.rows} circuit rows · "
                        f"{dtx_meta.families} families"):
                with ui.row().classes("gap-2 flex-wrap"):
                    if corr.matched:
                        c.chip("ok", f"{len(corr.matched)} file(s) match")
                    for f in corr.warnings:
                        c.chip("review", f"{f.harness or f.filename}: {f.detail}")
                    for f in corr.blocking:
                        c.chip("blocker", f"{f.harness or f.filename}: {f.detail}")
                if corr.blocking:
                    ui.label("Findings below mix build phases or programmes — "
                             "fix the inputs before trusting them.") \
                        .classes("text-xs").style(f"color:{theme.STATUS['blocker']}")

        def _render_summary(analyses) -> None:
            covered = [a for a in analyses if a.builds]
            findings = sum(len(a.findings) for a in analyses)
            circuits = sum(len(a.circuits) for a in analyses)
            with c.card("Summary"):
                with ui.row().classes("gap-2 flex-wrap"):
                    c.chip("info", f"{circuits} circuits across "
                                   f"{len(analyses)} families")
                    c.chip("ok", f"{len(covered)} family(ies) with a complexity file")
                    if len(analyses) - len(covered):
                        c.chip("review", f"{len(analyses) - len(covered)} without one")
                    c.chip("blocker" if findings else "ok",
                           f"{findings} circuit(s) never built")

        def _render_harnesses(analyses) -> None:
            for a in sorted(analyses, key=lambda x: (-len(x.findings), x.harness)):
                counts = a.counts
                subtitle = (f"def {a.def_id or '—'} · {a.builds} build(s) · "
                            + " · ".join(f"{v} {k}" for k, v in counts.items() if v))
                with ui.expansion().classes("w-full sx-card").props("dense") as exp:
                    with exp.add_slot("header"):
                        with ui.row().classes("items-center gap-3 w-full py-1 flex-wrap"):
                            c.chip("blocker" if a.findings else "ok",
                                   f"{len(a.findings)} never built")
                            ui.label(a.harness).classes("text-sm font-semibold")
                            ui.label(subtitle).classes("text-xs sx-muted")
                    if a.untracked_codes:
                        c.chip("review", "complexity does not track: "
                                         + ", ".join(a.untracked_codes))
                    rows = [{
                        "circuit": x.circuit,
                        "verdict": x.classification,
                        "condition": x.expression or "(none)",
                        "builds": f"{len(x.builds_with)}/{x.build_count}"
                                  if x.build_count else "—",
                        "carried_by": ", ".join(x.builds_with[:6])
                                      + ("…" if len(x.builds_with) > 6 else ""),
                        "untracked": ", ".join(x.untracked_codes),
                        "pins": ", ".join(x.pins[:4]),
                    } for x in a.circuits]
                    ui.table(rows=rows, columns=[
                        {"name": "circuit", "label": "Circuit", "field": "circuit",
                         "align": "left", "sortable": True},
                        {"name": "verdict", "label": "Verdict", "field": "verdict",
                         "align": "left", "sortable": True},
                        {"name": "condition", "label": "Sales-code condition",
                         "field": "condition", "align": "left"},
                        {"name": "builds", "label": "Builds", "field": "builds",
                         "align": "center", "sortable": True},
                        {"name": "carried_by", "label": "Carried by",
                         "field": "carried_by", "align": "left"},
                        {"name": "untracked", "label": "Untracked codes",
                         "field": "untracked", "align": "left"},
                        {"name": "pins", "label": "Pins", "field": "pins",
                         "align": "left"},
                    ], pagination=25).classes("w-full").props("dense flat")

        render()

        async def run() -> None:
            if not state["dtx"] or not state["complexity"]:
                ui.notify("Load the DTx and at least one complexity file",
                          type="warning")
                return

            def work(report):
                report(0.05, "Reading the DTx…")
                name, data = state["dtx"]
                rows, dtx_meta = read_dtx_circuits(data, name)

                harnesses, metas = {}, []
                total = len(state["complexity"])
                for i, (fname, payload) in enumerate(state["complexity"].items(), 1):
                    report(0.1 + 0.6 * (i - 1) / total,
                           f"Reading complexity {i} of {total} — {fname}")
                    try:
                        harness, meta = read_harness_file(payload, fname)
                    except Exception as exc:      # keep going; report at the end
                        metas.append(type("M", (), {
                            "filename": fname, "harness": "", "program": "",
                            "phase": "", "complete": False, "detail": str(exc)})())
                        continue
                    metas.append(meta)
                    harnesses[meta.harness or harness.name] = harness

                report(0.75, "Checking programme and phase…")
                corr = correspond.check(dtx_meta, metas)

                report(0.85, "Resolving circuits against the build tables…")
                families = {r.harness_family for r in rows}
                lookup = {k.upper().replace(" ", "_"): v for k, v in harnesses.items()}

                def match(family: str):
                    key = family.upper().replace(" ", "_")
                    return harnesses.get(family) or lookup.get(key)

                analyses = analyze(rows, harnesses, match=match)
                report(1.0, "Done")
                return dtx_meta, corr, analyses

            out = await c.run_engine_progress(
                work, progress_box, running="Analyzing…", done="Analysis ready")
            if out is not None:
                state["result"] = out
                render.refresh()
