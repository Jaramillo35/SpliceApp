"""Circuit Applicability workbench.

Three stages, in order:

1. **Load** the DTx and the individual complexity files.
2. **Map** each DTx harness family to its complexity file. Families auto-match
   by name; the rest are connected by dragging a file from the pool. The
   analysis runs ONLY where a mapping exists, because attributing one
   harness's builds to another family produces a confident wrong answer.
3. **Review** circuits, connectors (CNUM) and sales-code gaps per family.
"""

from __future__ import annotations

import re

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme

ROW_H = 52          # px; left, connector and right cells share it so lines align
GREEN = "#3fb950"
RED = "#f85149"

VERDICT_KIND = {
    "unconditional": "ok", "all builds": "ok", "variant": "info",
    "never built": "blocker", "no complexity": "review",
}


def _norm(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def _line(matched: bool) -> str:
    """The connector between a family and its complexity file."""
    if matched:
        return (f'<svg width="100%" height="{ROW_H}">'
                f'<line x1="0" y1="{ROW_H//2}" x2="100%" y2="{ROW_H//2}" '
                f'stroke="{GREEN}" stroke-width="2"/>'
                f'<circle cx="6" cy="{ROW_H//2}" r="4" fill="{GREEN}"/>'
                f'<circle cx="calc(100% - 6px)" cy="{ROW_H//2}" r="4" fill="{GREEN}"/>'
                f'</svg>')
    return (f'<svg width="100%" height="{ROW_H}">'
            f'<line x1="0" y1="{ROW_H//2}" x2="100%" y2="{ROW_H//2}" '
            f'stroke="{RED}" stroke-width="2" stroke-dasharray="6,5"/>'
            f'<circle cx="6" cy="{ROW_H//2}" r="4" fill="none" stroke="{RED}" '
            f'stroke-width="2"/></svg>')


def _guide() -> None:
    with ui.expansion("How this works — read me first", icon="school") \
            .classes("w-full").props("dense"):
        ui.markdown(
            "**The question.** For one harness family: which circuits and "
            "connectors does the DTx put on it, under which sales-code "
            "conditions, and which of that harness's part numbers actually "
            "carry each one?\n\n"
            "**Mapping first.** A DTx family is analyzed only once it is "
            "connected to a complexity file — a **green solid line**. A **red "
            "dotted line** means nothing is connected and that family is "
            "skipped. Drag a file from the pool onto a family to connect it; "
            "click ✕ to disconnect and return it to the pool.\n\n"
            "**Verdicts.** *unconditional* — no sales code, every build has "
            "it. *all builds* — conditioned but true for every build. "
            "*variant* — some part numbers only. **never built** — the "
            "condition holds for no build of this harness: either the circuit "
            "does not belong here, or a part number is missing a code.\n\n"
            "**Sales-code gaps.** A code the DTx conditions on that the "
            "complexity file does not track is *unknown, not absent*, so it is "
            "read as present. That can only make a circuit look wider, never "
            "invent a missing one — but every circuit resting on such a code "
            "is reading wider than the data can justify, which is what the "
            "Sales-code gaps tab lists."
        ).classes("text-sm")


@ui.page("/circuit-applicability")
def page() -> None:
    from splice.dtxcircuits import analyze_harness, correspond, read_dtx_circuits
    from splice.dtxcircuits.complexity import read_harness_file

    state: dict = {
        "dtx": None, "uploads": {},
        "rows": [], "dtx_meta": None, "families": [],
        "harnesses": {},        # filename -> Harness
        "metas": {},            # filename -> ComplexityMeta
        "mapping": {},          # family -> filename
        "corr": None, "analyses": {}, "selected": None, "drag": None,
    }

    with c.frame("Circuit Applicability",
                 "DTx circuits × harness complexity — mapped, then resolved "
                 "per circuit and per connector."):
        _guide()

        with c.card("1 · Inputs",
                    "Programme and phase are read from inside both file types "
                    "— the DTx title block and each complexity file's Harness "
                    "PN sheet — never from the filenames."):
            with ui.row().classes("w-full gap-4 flex-wrap"):
                c.upload_zone("Detailed DTx Circuits Report",
                              lambda n, b: state.update(dtx=(n, b)),
                              accept=".xls,.xlsx,.xlsm")
                c.upload_zone("Individual harness complexity file(s)",
                              lambda n, b: state["uploads"].__setitem__(n, b),
                              accept=".xlsm,.xlsx", multiple=True)
            ui.button("Load and match", icon="link",
                      on_click=lambda: load()).props("unelevated")
            progress = ui.column().classes("w-full gap-1")

        # ---------------------------------------------------------------- map
        @ui.refreshable
        def mapping_view() -> None:
            if not state["families"]:
                return
            meta = state["dtx_meta"]
            mapped = state["mapping"]
            pool = [f for f in state["harnesses"] if f not in mapped.values()]

            with c.card("2 · Map families to complexity files",
                        f"DTx {meta.program or '?'} · phase {meta.phase or '?'} "
                        f"· {len(state['families'])} families · "
                        f"{len(state['harnesses'])} complexity file(s) loaded"):
                with ui.row().classes("gap-2 flex-wrap"):
                    c.chip("ok", f"{len(mapped)} connected")
                    if len(state["families"]) - len(mapped):
                        c.chip("blocker",
                               f"{len(state['families']) - len(mapped)} not connected")
                    if pool:
                        c.chip("review", f"{len(pool)} file(s) unused")
                    for f in (state["corr"].blocking if state["corr"] else []):
                        c.chip("blocker", f"{f.filename}: {f.detail}")
                    for f in (state["corr"].warnings if state["corr"] else []):
                        c.chip("review", f"{f.filename}: {f.detail}")

                # header
                with ui.element("div").classes("w-full grid gap-2 mt-2") \
                        .style("grid-template-columns: 1fr 120px 1.4fr"):
                    ui.label("DTx harness family").classes("text-xs font-bold sx-muted")
                    ui.label("").classes("text-xs")
                    ui.label("Individual complexity file").classes(
                        "text-xs font-bold sx-muted")

                for family, n_rows in state["families"]:
                    filename = mapped.get(family)
                    with ui.element("div").classes("w-full grid gap-2 items-center") \
                            .style("grid-template-columns: 1fr 120px 1.4fr"):
                        # left — the DTx family
                        with ui.element("div").classes(
                                "rounded-lg px-3 flex flex-col justify-center") \
                                .style(f"height:{ROW_H}px;background:{theme.SURFACE_2};"
                                       f"border:1px solid {theme.LINE}"):
                            ui.label(family).classes("text-sm font-semibold")
                            ui.label(f"{n_rows} DTx row(s)").classes("text-xs sx-muted")
                        # middle — the connector
                        ui.html(_line(bool(filename)))
                        # right — the complexity file, or a drop zone
                        _target_cell(family, filename)

                if pool:
                    ui.label("Unmatched complexity files — drag one onto a family") \
                        .classes("text-xs font-bold sx-muted mt-3")
                    with ui.row().classes("gap-2 flex-wrap"):
                        for filename in sorted(pool):
                            _pool_item(filename)
                else:
                    ui.label("Every loaded complexity file is connected.") \
                        .classes("text-xs sx-muted mt-2")

                with ui.row().classes("items-center gap-3 mt-3"):
                    ui.button("Run analysis", icon="play_arrow",
                              on_click=lambda: run()).props("unelevated") \
                        .set_enabled(bool(mapped))
                    ui.label("Only connected families are analyzed.") \
                        .classes("text-xs sx-muted")

        def _target_cell(family: str, filename: str | None) -> None:
            """Right-hand cell: the connected file, or a drop zone."""
            border = f"1px solid {theme.LINE}" if filename \
                else f"1px dashed {RED}88"
            cell = ui.element("div").classes(
                "rounded-lg px-3 flex items-center justify-between gap-2") \
                .style(f"height:{ROW_H}px;background:{theme.SURFACE_2};border:{border}")
            with cell:
                if filename:
                    meta = state["metas"].get(filename)
                    harness = state["harnesses"].get(filename)
                    with ui.column().classes("gap-0 min-w-0"):
                        ui.label(filename).classes("text-xs font-semibold truncate")
                        detail = " · ".join(x for x in (
                            f"def {harness.def_id}" if harness else "",
                            f"{len(harness.builds)} build(s)" if harness else "",
                            f"{len(harness.complexity_codes)} code(s)" if harness else "",
                            f"{meta.phase}" if meta and meta.phase else "") if x)
                        ui.label(detail).classes("text-xs sx-muted truncate")
                    ui.button(icon="close", on_click=lambda f=family: _unmap(f)) \
                        .props("flat dense round size=sm")
                else:
                    ui.label("drop a complexity file here").classes("text-xs") \
                        .style(f"color:{RED}")
            cell.on("dragover.prevent", lambda: None)
            cell.on("drop", lambda _e, f=family: _drop(f))

        def _pool_item(filename: str) -> None:
            harness = state["harnesses"].get(filename)
            meta = state["metas"].get(filename)
            item = ui.element("div").classes(
                "rounded-lg px-3 py-2 cursor-grab") \
                .style(f"background:{theme.SURFACE_2};border:1px solid {theme.LINE}")
            with item:
                ui.label(meta.harness if meta and meta.harness else filename) \
                    .classes("text-xs font-semibold")
                ui.label(f"{filename}" + (f" · {len(harness.builds)} build(s)"
                                          if harness else "")) \
                    .classes("text-[10px] sx-muted")
            item.props("draggable")
            item.on("dragstart", lambda _e, f=filename: state.update(drag=f))

        def _drop(family: str) -> None:
            filename = state.get("drag")
            if not filename:
                return
            # a file belongs to one family at a time
            for fam, name in list(state["mapping"].items()):
                if name == filename:
                    state["mapping"].pop(fam)
            state["mapping"][family] = filename
            state["drag"] = None
            state["analyses"] = {}
            mapping_view.refresh()
            results_view.refresh()

        def _unmap(family: str) -> None:
            state["mapping"].pop(family, None)
            state["analyses"] = {}
            mapping_view.refresh()
            results_view.refresh()

        mapping_view()

        # ------------------------------------------------------------ results
        @ui.refreshable
        def results_view() -> None:
            analyses = state["analyses"]
            if not analyses:
                return
            names = sorted(analyses)
            if state["selected"] not in analyses:
                state["selected"] = names[0]

            with c.card("3 · Review"):
                with ui.row().classes("w-full gap-4 items-start no-wrap"):
                    # master — families
                    with ui.column().classes("gap-1 min-w-[15rem]"):
                        ui.label("FAMILIES").classes(
                            "text-[10px] font-bold tracking-widest sx-muted")
                        for name in names:
                            a = analyses[name]
                            n_find = len(a.findings) + len(a.cnum_findings)
                            active = name == state["selected"]
                            row = ui.element("div").classes(
                                "rounded-lg px-2 py-1.5 cursor-pointer w-full") \
                                .style(f"background:{theme.BRAND}26" if active
                                       else f"background:{theme.SURFACE_2}")
                            with row:
                                with ui.row().classes("items-center gap-2 no-wrap"):
                                    ui.icon("report" if n_find else "check_circle") \
                                        .classes("text-sm") \
                                        .style(f"color:{RED if n_find else GREEN}")
                                    with ui.column().classes("gap-0 min-w-0"):
                                        ui.label(name).classes("text-xs font-semibold truncate")
                                        ui.label(f"{len(a.circuits)} ckt · "
                                                 f"{len(a.cnums)} cnum"
                                                 + (f" · {n_find} finding(s)" if n_find else "")) \
                                            .classes("text-[10px] sx-muted")
                            row.on("click", lambda _e, n=name: (
                                state.update(selected=n), results_view.refresh()))
                    # detail
                    with ui.column().classes("flex-1 min-w-0 gap-2"):
                        _detail(analyses[state["selected"]])

        def _detail(a) -> None:
            with ui.row().classes("gap-2 flex-wrap"):
                c.chip("info", f"def {a.def_id or '—'} · {a.builds} build(s)")
                for label, n in a.counts.items():
                    if n:
                        c.chip(VERDICT_KIND.get(label, "info"), f"{n} {label}")
            with ui.tabs().props("dense align=left") as tabs:
                t_ckt = ui.tab(f"Circuits ({len(a.circuits)})")
                t_cnum = ui.tab(f"Connectors ({len(a.cnums)})")
                t_gap = ui.tab(f"Sales-code gaps ({len(a.code_gaps)})")
            with ui.tab_panels(tabs, value=t_ckt).classes("w-full"):
                with ui.tab_panel(t_ckt).classes("p-0 pt-2"):
                    _circuit_table(a)
                with ui.tab_panel(t_cnum).classes("p-0 pt-2"):
                    _cnum_table(a)
                with ui.tab_panel(t_gap).classes("p-0 pt-2"):
                    _gap_view(a)

        def _circuit_table(a) -> None:
            rows = [{
                "circuit": x.circuit, "verdict": x.classification,
                "condition": x.expression or "(none)",
                "builds": f"{len(x.builds_with)}/{x.build_count}" if x.build_count else "—",
                "carried_by": ", ".join(x.builds_with[:5])
                              + ("…" if len(x.builds_with) > 5 else ""),
                "untracked": ", ".join(x.untracked_codes),
                "pins": ", ".join(x.pins[:4]),
            } for x in sorted(a.circuits, key=lambda x: (not x.is_finding, x.circuit))]
            ui.table(rows=rows, columns=[
                {"name": "circuit", "label": "Circuit", "field": "circuit",
                 "align": "left", "sortable": True},
                {"name": "verdict", "label": "Verdict", "field": "verdict",
                 "align": "left", "sortable": True},
                {"name": "condition", "label": "Condition", "field": "condition",
                 "align": "left"},
                {"name": "builds", "label": "Builds", "field": "builds",
                 "align": "center", "sortable": True},
                {"name": "carried_by", "label": "Carried by", "field": "carried_by",
                 "align": "left"},
                {"name": "untracked", "label": "Untracked", "field": "untracked",
                 "align": "left"},
                {"name": "pins", "label": "Pins", "field": "pins", "align": "left"},
            ], pagination=20).classes("w-full").props("dense flat")

        def _cnum_table(a) -> None:
            rows = [{
                "cnum": x.cnum, "connector": x.connector_pn,
                "verdict": x.classification,
                "condition": x.expression or "(none)",
                "builds": f"{len(x.builds_with)}/{x.build_count}" if x.build_count else "—",
                "circuits": f"{len(x.circuits)}",
                "circuit_list": ", ".join(x.circuits[:6])
                                + ("…" if len(x.circuits) > 6 else ""),
                "untracked": ", ".join(x.untracked_codes),
            } for x in sorted(a.cnums, key=lambda x: (not x.is_finding, x.cnum))]
            ui.table(rows=rows, columns=[
                {"name": "cnum", "label": "CNUM", "field": "cnum",
                 "align": "left", "sortable": True},
                {"name": "connector", "label": "Connector PN", "field": "connector",
                 "align": "left"},
                {"name": "verdict", "label": "Verdict", "field": "verdict",
                 "align": "left", "sortable": True},
                {"name": "condition", "label": "Condition", "field": "condition",
                 "align": "left"},
                {"name": "builds", "label": "Builds", "field": "builds",
                 "align": "center", "sortable": True},
                {"name": "circuits", "label": "# ckt", "field": "circuits",
                 "align": "center", "sortable": True},
                {"name": "circuit_list", "label": "Circuits", "field": "circuit_list",
                 "align": "left"},
                {"name": "untracked", "label": "Untracked", "field": "untracked",
                 "align": "left"},
            ], pagination=20).classes("w-full").props("dense flat")

        def _gap_view(a) -> None:
            ui.label("Sales codes the DTx conditions on for this family that its "
                     "complexity file does not track. They are read as PRESENT, "
                     "so every circuit below applies more widely than the data "
                     "can justify.").classes("text-xs sx-muted")
            if not a.code_gaps:
                c.chip("ok", "Every code the DTx uses here is tracked")
            else:
                ui.table(rows=[{
                    "code": g.code, "uses": g.occurrences,
                    "circuits": ", ".join(g.circuits[:8])
                                + ("…" if len(g.circuits) > 8 else ""),
                    "cnums": ", ".join(g.cnums[:8])
                             + ("…" if len(g.cnums) > 8 else ""),
                } for g in a.code_gaps], columns=[
                    {"name": "code", "label": "Sales code", "field": "code",
                     "align": "left", "sortable": True},
                    {"name": "uses", "label": "DTx rows", "field": "uses",
                     "align": "center", "sortable": True},
                    {"name": "circuits", "label": "Circuits affected",
                     "field": "circuits", "align": "left"},
                    {"name": "cnums", "label": "Connectors affected",
                     "field": "cnums", "align": "left"},
                ], pagination=15).classes("w-full").props("dense flat")
            if a.unused_codes:
                ui.label("Tracked by the complexity file but never conditioned on "
                         "by a DTx circuit in this family:").classes(
                    "text-xs sx-muted mt-2")
                ui.label(", ".join(a.unused_codes)).classes("text-xs sx-mono")

        results_view()

        # ------------------------------------------------------------ actions
        async def load() -> None:
            if not state["dtx"] or not state["uploads"]:
                ui.notify("Load the DTx and at least one complexity file",
                          type="warning")
                return

            def work(report):
                report(0.05, "Reading the DTx…")
                name, data = state["dtx"]
                rows, meta = read_dtx_circuits(data, name)

                harnesses, metas, failed = {}, {}, []
                total = len(state["uploads"])
                for i, (fname, payload) in enumerate(state["uploads"].items(), 1):
                    report(0.1 + 0.7 * (i - 1) / total,
                           f"Reading complexity {i} of {total} — {fname}")
                    try:
                        harness, cmeta = read_harness_file(payload, fname)
                    except Exception as exc:
                        failed.append(f"{fname}: {exc}")
                        continue
                    harnesses[fname] = harness
                    metas[fname] = cmeta

                report(0.85, "Checking programme and phase…")
                corr = correspond.check(meta, list(metas.values()))

                report(0.92, "Auto-matching families…")
                families = sorted({r.harness_family for r in rows})
                counts = {f: sum(1 for r in rows if r.harness_family == f)
                          for f in families}
                by_name = {}
                for fname, cmeta in metas.items():
                    key = _norm(cmeta.harness or harnesses[fname].name)
                    by_name.setdefault(key, fname)
                mapping = {f: by_name[_norm(f)] for f in families
                           if _norm(f) in by_name}
                report(1.0, "Done")
                return (rows, meta, [(f, counts[f]) for f in families],
                        harnesses, metas, mapping, corr, failed)

            out = await c.run_engine_progress(
                work, progress, running="Reading files…", done="Files loaded")
            if out is None:
                return
            rows, meta, families, harnesses, metas, mapping, corr, failed = out
            state.update(rows=rows, dtx_meta=meta, families=families,
                         harnesses=harnesses, metas=metas, mapping=mapping,
                         corr=corr, analyses={}, selected=None)
            for problem in failed[:5]:
                ui.notify(problem, type="negative", multi_line=True,
                          close_button=True)
            ui.notify(f"{len(mapping)} of {len(families)} families matched "
                      "automatically", type="positive")
            mapping_view.refresh()
            results_view.refresh()

        async def run() -> None:
            if not state["mapping"]:
                ui.notify("Connect at least one family first", type="warning")
                return

            def work(report):
                rows = state["rows"]
                mapping = state["mapping"]
                out = {}
                for i, (family, filename) in enumerate(sorted(mapping.items()), 1):
                    report(i / max(len(mapping), 1),
                           f"Resolving {family} ({i} of {len(mapping)})…")
                    family_rows = [r for r in rows if r.harness_family == family]
                    out[family] = analyze_harness(
                        family_rows, state["harnesses"][filename],
                        harness_name=family)
                return out

            out = await c.run_engine_progress(
                work, progress, running="Analyzing…", done="Analysis ready")
            if out is not None:
                state["analyses"] = out
                state["selected"] = None
                results_view.refresh()
