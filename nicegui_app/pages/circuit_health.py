"""Circuit Health — the SE review workbench.

The overview is the filter: a harness-pair matrix, a kind breakdown, and a
circuit-impact chart all scope the queue when clicked. A master-detail split
keeps the list compact and draws each finding — the two harnesses, the inline
between them, and which builds carry the wire versus not — so evidence is
read visually, not parsed out of expressions. Dispositions live in the detail
pane; progress burns down in the strip up top.

Absorbs Inline Continuity (the audit tab); the engine is splice.inline.health
unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme
from splice.config import DATA_DIR
from splice.inline import health
from splice.inline.complexity import read_complexity
from splice.inline.pairing import resolve
from splice.inline.summary import read_circuit_summary

BASELINE_PATH = DATA_DIR / "inline_health" / "baseline.json"
SEV_KIND = {"Blocker": "blocker", "High": "high", "Review": "review"}
SEV_ORDER = ["Blocker", "High", "Review"]
KIND_LABEL = {"cavity": "Cavity mismatch", "one_sided_window": "Missing variant window",
              "route_window_gap": "Route gap"}


# --------------------------------------------------------------------------- pure helpers

def pair_key(f) -> tuple[str, str]:
    a, b = f.harness_with or "?", f.harness_without or f.harness_with or "?"
    return tuple(sorted((a, b)))


def filter_findings(findings, filters: dict) -> list:
    out = []
    query = (filters.get("query") or "").strip().upper()
    for f in findings:
        if filters.get("severities") and f.severity not in filters["severities"]:
            continue
        if filters.get("kind") and f.kind != filters["kind"]:
            continue
        if filters.get("pair") and pair_key(f) != tuple(filters["pair"]):
            continue
        if query and query not in f"{f.circuit} {f.inline}".upper():
            continue
        out.append(f)
    return out


def matrix_data(open_findings) -> dict:
    """Harness-pair heatmap: cell = open findings, colored by worst severity."""
    cells: dict[tuple[str, str], dict] = {}
    for f in open_findings:
        key = pair_key(f)
        cell = cells.setdefault(key, {"count": 0, "worst": "Review"})
        cell["count"] += 1
        if SEV_ORDER.index(f.severity) < SEV_ORDER.index(cell["worst"]):
            cell["worst"] = f.severity
    names = sorted({n for key in cells for n in key})
    index = {n: i for i, n in enumerate(names)}
    data = []
    for (a, b), cell in cells.items():
        color = theme.STATUS[SEV_KIND[cell["worst"]]]
        data.append({"value": [index[a], index[b], cell["count"]],
                     "pair": [a, b],
                     "itemStyle": {"color": color, "borderRadius": 3}})
        if a != b:
            data.append({"value": [index[b], index[a], cell["count"]],
                         "pair": [a, b],
                         "itemStyle": {"color": color, "borderRadius": 3}})
    return {"names": names, "data": data}


def matrix_options(open_findings) -> dict:
    m = matrix_data(open_findings)
    axis = {"type": "category", "data": m["names"],
            "axisLabel": {"color": "rgba(232,232,236,0.75)", "fontSize": 10,
                          "rotate": 35},
            "splitLine": {"show": False}, "axisTick": {"show": False}}
    return {
        "backgroundColor": "transparent",
        "grid": {"left": 110, "right": 12, "top": 8, "bottom": 70},
        "xAxis": axis,
        "yAxis": {**axis, "axisLabel": {**axis["axisLabel"], "rotate": 0}},
        "series": [{"type": "heatmap", "data": m["data"],
                    "label": {"show": True, "color": "#0e1117",
                              "fontWeight": "bold",
                              "formatter": "{@[2]}"},
                    "emphasis": {"itemStyle": {"shadowBlur": 6}}}],
        "tooltip": {"formatter": "{b}: {c}"},
    }


def kind_bar_options(open_findings) -> dict:
    counts = {label: 0 for label in KIND_LABEL.values()}
    for f in open_findings:
        counts[KIND_LABEL.get(f.kind, f.kind)] = \
            counts.get(KIND_LABEL.get(f.kind, f.kind), 0) + 1
    labels = [k for k, v in counts.items() if v]
    return {
        "backgroundColor": "transparent",
        "grid": {"left": 150, "right": 24, "top": 8, "bottom": 24},
        "xAxis": {"type": "value",
                  "axisLabel": {"color": "rgba(232,232,236,0.6)"},
                  "splitLine": {"lineStyle": {"color": "rgba(232,232,236,0.08)"}}},
        "yAxis": {"type": "category", "data": labels,
                  "axisLabel": {"color": "rgba(232,232,236,0.8)"}},
        "series": [{"type": "bar", "data": [counts[k] for k in labels],
                    "barWidth": 12,
                    "itemStyle": {"color": theme.CHART[1],
                                   "borderRadius": [0, 4, 4, 0]}}],
        "tooltip": {},
    }


def circuit_bar_options(open_findings, top: int = 10) -> dict:
    impact: dict[str, int] = {}
    for f in open_findings:
        for circuit in (f.circuit or "?").split(","):
            circuit = circuit.strip()
            if circuit:
                impact[circuit] = impact.get(circuit, 0) \
                    + max(len(f.builds_without), len(f.builds_with), 1)
    ranked = sorted(impact.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return {
        "backgroundColor": "transparent",
        "grid": {"left": 70, "right": 24, "top": 8, "bottom": 24},
        "xAxis": {"type": "value",
                  "axisLabel": {"color": "rgba(232,232,236,0.6)"},
                  "splitLine": {"lineStyle": {"color": "rgba(232,232,236,0.08)"}}},
        "yAxis": {"type": "category",
                  "data": [k for k, _ in reversed(ranked)],
                  "axisLabel": {"color": "rgba(232,232,236,0.8)",
                                "fontFamily": "monospace"}},
        "series": [{"type": "bar", "data": [v for _, v in reversed(ranked)],
                    "barWidth": 12,
                    "itemStyle": {"color": theme.CHART[0],
                                   "borderRadius": [0, 4, 4, 0]}}],
        "tooltip": {"formatter": "{b}: {c} affected build(s)"},
    }


def progress_segments(result, baseline) -> list[tuple[str, float, str]]:
    """(color, fraction, label) segments: dispositioned + open by severity."""
    total = len(result.findings)
    if not total:
        return []
    open_f = result.open_findings(baseline)
    done = total - len(open_f)
    segments = []
    if done:
        segments.append((theme.STATUS["ok"], done / total, f"{done} dispositioned"))
    for sev in SEV_ORDER:
        n = sum(1 for f in open_f if f.severity == sev)
        if n:
            segments.append((theme.STATUS[SEV_KIND[sev]], n / total,
                             f"{n} {sev.lower()} open"))
    return segments


# --------------------------------------------------------------------------- page

@ui.page("/circuit-health")
def page() -> None:
    state: dict = {"summary": None, "cx": {}, "result": None, "rejected": [],
                   "filters": {"severities": set(), "kind": None,
                               "pair": None, "query": ""},
                   "selected": None, "engineer": "SE"}

    auto_dir = os.getenv("SPLICE_HEALTH_AUTOLOAD")
    if auto_dir and Path(auto_dir).is_dir():
        d = Path(auto_dir)
        s = next(iter(d.glob("Circuit Summary*.xlsx")), None)
        if s is not None:
            state["summary"] = (s.name, s.read_bytes())
        for f in sorted(d.glob("*.xls[mM]")):
            state["cx"][f.name] = f.read_bytes()

    with c.frame("Circuit Health",
                 "The review workbench: the charts are the filters — click a "
                 "matrix cell, a kind, or a circuit to scope the queue."):

        # ---------------- header: metrics + progress ----------------------
        @ui.refreshable
        def header() -> None:
            r = state["result"]
            if not r:
                return
            baseline = health.load_baseline(BASELINE_PATH)
            open_f = r.open_findings(baseline)
            with ui.row().classes("gap-4 flex-wrap items-center"):
                for label, value, kind in [
                        ("Blockers open",
                         sum(1 for f in open_f if f.severity == "Blocker"), "blocker"),
                        ("High open",
                         sum(1 for f in open_f if f.severity == "High"), "high"),
                        ("Review open",
                         sum(1 for f in open_f if f.severity == "Review"), "review"),
                        ("Dispositioned",
                         len(r.findings) - len(open_f), "ok"),
                        ("Auto-cleared", len(r.cleared), "info")]:
                    with ui.card().classes("sx-card px-4 py-2 items-center gap-0"):
                        ui.label(str(value)).classes("text-2xl font-bold leading-none") \
                            .style(f"color:{theme.STATUS[kind]}")
                        ui.label(label).classes("text-[11px] sx-muted")
            segments = progress_segments(r, baseline)
            if segments:
                with ui.row().classes("w-full h-2 rounded-full overflow-hidden gap-0"):
                    for color, fraction, _ in segments:
                        ui.element("div").style(
                            f"background:{color};width:{fraction * 100:.2f}%")
                ui.label(" · ".join(s[2] for s in segments)).classes("text-xs sx-muted")

        header()

        # ---------------- inputs ------------------------------------------
        with ui.expansion("Inputs", value=state["result"] is None) \
                .classes("w-full sx-card px-2").props("dense"):
            ui.label("Circuit Summary + one Harness Complexity per harness — "
                     "matched by the DEF id inside each file.") \
                .classes("text-sm sx-muted")
            with ui.row().classes("w-full gap-4 flex-wrap"):
                c.upload_zone("Circuit Summary (.xlsx)",
                              lambda n, b: state.update(summary=(n, b)),
                              accept=".xlsx")
                c.upload_zone("Complexity files (.xlsm)",
                              lambda n, b: state["cx"].__setitem__(n, b),
                              accept=".xlsm,.xlsx", multiple=True)
            if state["summary"]:
                ui.label(f"Preloaded: {state['summary'][0]} + "
                         f"{len(state['cx'])} complexity file(s)") \
                    .classes("text-xs sx-muted")
            ui.button("Run health check", icon="play_arrow",
                      on_click=lambda: run_check()).props("unelevated")

        # ---------------- workbench ---------------------------------------
        @ui.refreshable
        def workbench() -> None:
            r = state["result"]
            if not r:
                c.empty("Run the health check to open the workbench.")
                return
            baseline = health.load_baseline(BASELINE_PATH)
            dispositions = baseline.get("dispositions", {})
            open_f = r.open_findings(baseline)

            gate0(r)

            with ui.tabs().props("dense align=left") as tabs:
                t_work = ui.tab(f"Workbench ({len(open_f)} open)")
                t_done = ui.tab(f"Dispositioned "
                                f"({len(r.findings) - len(open_f)})")
                t_clear = ui.tab(f"Auto-cleared ({len(r.cleared)})")
                t_audit = ui.tab("Continuity audit")
            with ui.tab_panels(tabs, value=t_work).classes("w-full"):
                with ui.tab_panel(t_work).classes("p-0 pt-2"):
                    work_tab(open_f, dispositions)
                with ui.tab_panel(t_done).classes("p-0 pt-2"):
                    done_f = [f for f in r.findings if f not in open_f]
                    for f in done_f:
                        with ui.row().classes("items-center gap-2 w-full"):
                            c.chip("ok", dispositions[f.fingerprint]["verdict"])
                            ui.label(f"{KIND_LABEL.get(f.kind, f.kind)} · "
                                     f"{f.inline} · {f.circuit}") \
                                .classes("text-sm sx-muted")
                with ui.tab_panel(t_clear).classes("p-0 pt-2"):
                    for p in r.cleared[:300]:
                        ui.label(f"{p.inline} · cav {p.cavity} · {p.window}") \
                            .classes("text-xs sx-mono sx-muted")
                with ui.tab_panel(t_audit).classes("p-0 pt-2"):
                    audit_tab(r)

            signoff(r, baseline)

        def gate0(r) -> None:
            issues = list(state["rejected"])
            if r.inputs.missing_complexity:
                issues.append("Missing complexity: "
                              + ", ".join(r.inputs.missing_complexity))
            if r.inputs.skew_days > 30:
                issues.append(f"Revision skew {r.inputs.skew_days} days — "
                              f"{r.inputs.skew_pair}")
            if issues:
                with ui.row().classes("gap-2 flex-wrap"):
                    for issue in issues:
                        c.chip("high", issue)

        # ------------- the workbench tab ----------------------------------
        def work_tab(open_f, dispositions) -> None:
            filters = state["filters"]

            with ui.row().classes("w-full gap-3 flex-wrap"):
                with ui.card().classes("sx-card flex-1 min-w-[22rem]"):
                    ui.label("Where — open findings per harness pair "
                             "(click a cell to scope)") \
                        .classes("text-xs font-bold sx-muted")
                    ui.echart(matrix_options(open_f),
                              on_point_click=lambda e: set_pair(e)) \
                        .classes("w-full h-64")
                    with ui.row().classes("gap-3"):
                        for sev in SEV_ORDER:
                            c.chip(SEV_KIND[sev], sev)
                with ui.column().classes("flex-1 min-w-[20rem] gap-3"):
                    with ui.card().classes("sx-card w-full"):
                        ui.label("What kind").classes("text-xs font-bold sx-muted")
                        ui.echart(kind_bar_options(open_f),
                                  on_point_click=lambda e: set_kind(e)) \
                            .classes("w-full h-28")
                    with ui.card().classes("sx-card w-full"):
                        ui.label("Top circuits by affected builds "
                                 "(click to search)") \
                            .classes("text-xs font-bold sx-muted")
                        ui.echart(circuit_bar_options(open_f),
                                  on_point_click=lambda e: set_circuit(e)) \
                            .classes("w-full h-40")

            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                for sev in SEV_ORDER:
                    active = sev in filters["severities"]
                    ui.button(sev, on_click=lambda s=sev: toggle_sev(s)) \
                        .props(f"dense no-caps "
                               f"{'unelevated' if active else 'outline'}") \
                        .style(f"color:{'white' if active else theme.STATUS[SEV_KIND[sev]]};"
                               + (f"background:{theme.STATUS[SEV_KIND[sev]]}" if active else ""))
                search = ui.input(placeholder="circuit or inline…",
                                  value=filters["query"]).props("dense clearable") \
                    .classes("w-56")
                search.on_value_change(lambda e: set_query(e.value))
                if filters["pair"]:
                    ui.button(f"{filters['pair'][0]} ↔ {filters['pair'][1]} ✕",
                              on_click=clear_pair).props("dense outline no-caps")
                if filters["kind"]:
                    ui.button(f"{KIND_LABEL.get(filters['kind'])} ✕",
                              on_click=clear_kind).props("dense outline no-caps")

            visible = filter_findings(open_f, filters)
            ui.label(f"{len(visible)} of {len(open_f)} open findings") \
                .classes("text-xs sx-muted")

            with ui.splitter(value=55).classes("w-full") as splitter:
                with splitter.before:
                    with ui.column().classes("w-full gap-1 pr-3 max-h-[34rem] "
                                             "overflow-y-auto"):
                        for f in visible:
                            row_selected = state["selected"] == f.fingerprint
                            with ui.row().classes(
                                    "items-center gap-2 w-full px-2 py-1.5 rounded-lg "
                                    "cursor-pointer") \
                                    .style(f"background:{theme.BRAND}22"
                                           if row_selected else "") \
                                    .on("click", lambda f=f: select(f)):
                                c.chip(SEV_KIND[f.severity], f.severity[0])
                                ui.label(f.circuit or "—").classes(
                                    "text-sm font-semibold sx-mono w-24")
                                ui.label(f.inline).classes("text-sm sx-muted flex-1")
                                if f.builds_without:
                                    ui.label(f"{len(f.builds_without)} builds") \
                                        .classes("text-xs") \
                                        .style(f"color:{theme.STATUS['blocker']}")
                with splitter.after:
                    with ui.column().classes("w-full pl-3"):
                        detail(visible, dispositions)

        # ------------- detail pane ---------------------------------------
        def detail(visible, dispositions) -> None:
            f = next((x for x in visible
                      if x.fingerprint == state["selected"]), None)
            if f is None:
                c.empty("Select a finding to see its evidence.",
                        icon="fact_check")
                return
            with ui.row().classes("items-center gap-2 flex-wrap"):
                c.chip(SEV_KIND[f.severity], f.severity)
                c.chip("info", KIND_LABEL.get(f.kind, f.kind))
            ui.label(f.inline + (f" · cavity {f.cavity}" if f.cavity else "")
                     + (f" · {f.circuit}" if f.circuit else "")) \
                .classes("text-sm font-semibold")

            _diagram(f)

            if f.window:
                ui.label("Option window with no wire") \
                    .classes("text-xs font-bold sx-muted mt-1")
                ui.label(f.window).classes("text-xs sx-mono p-2 rounded w-full") \
                    .style(f"background:{theme.CANVAS}")
            ui.label(f.detail).classes("text-sm sx-muted")

            with ui.row().classes("w-full gap-4 flex-wrap mt-1"):
                if f.builds_with:
                    with ui.column().classes("gap-1"):
                        ui.label(f"Has the wire — {f.harness_with}") \
                            .classes("text-xs font-bold") \
                            .style(f"color:{theme.STATUS['ok']}")
                        with ui.row().classes("gap-1 flex-wrap max-w-xs"):
                            for pn in f.builds_with:
                                ui.label(pn).classes(
                                    "text-[10px] sx-mono px-1.5 py-0.5 rounded") \
                                    .style(f"background:{theme.STATUS['ok']}22;"
                                           f"color:{theme.STATUS['ok']}")
                if f.builds_without:
                    with ui.column().classes("gap-1"):
                        ui.label(f"No wire — {f.harness_without}") \
                            .classes("text-xs font-bold") \
                            .style(f"color:{theme.STATUS['blocker']}")
                        with ui.row().classes("gap-1 flex-wrap max-w-xs"):
                            for pn in f.builds_without:
                                ui.label(pn).classes(
                                    "text-[10px] sx-mono px-1.5 py-0.5 rounded") \
                                    .style(f"background:{theme.STATUS['blocker']}22;"
                                           f"color:{theme.STATUS['blocker']}")

            ui.separator().classes("my-2")
            d = dispositions.get(f.fingerprint)
            if d:
                c.chip("ok", f"{d['verdict']} — {d.get('by', '')}, {d.get('date', '')}")
                return
            reason = ui.input("Reason").classes("w-full").props("dense")
            with ui.row().classes("gap-2 flex-wrap"):
                for verdict, icon in [("Accepted variant", "check"),
                                      ("Defect", "bug_report"),
                                      ("By design", "architecture")]:
                    ui.button(verdict, icon=icon,
                              on_click=lambda v=verdict, f=f: dispose(
                                  f, v, reason.value)) \
                        .props("outline dense no-caps")

        def _diagram(f) -> None:
            """Two harnesses and the inline between them, drawn."""
            ok, bad = theme.STATUS["ok"], theme.STATUS["blocker"]
            one_sided = f.kind == "one_sided_window"
            with ui.row().classes("items-center w-full gap-0 my-2"):
                with ui.column().classes("items-center gap-0 px-3 py-2 rounded-lg") \
                        .style(f"background:{theme.SURFACE_2};border:1px solid {ok}66"):
                    ui.icon("cable").style(f"color:{ok}")
                    ui.label(f.harness_with).classes("text-xs font-semibold")
                ui.element("div").classes("flex-1 h-0.5") \
                    .style(f"background:{ok}")
                with ui.column().classes("items-center gap-0 px-2"):
                    ui.icon("settings_input_component").classes("text-lg") \
                        .style(f"color:{theme.BRAND}")
                    ui.label(f.inline.split(' ')[0] if one_sided else f.inline) \
                        .classes("text-[10px] sx-mono sx-muted")
                    if f.cavity:
                        ui.label(f"cav {f.cavity}").classes("text-[10px] sx-muted")
                ui.element("div").classes("flex-1 h-0.5") \
                    .style(f"background:repeating-linear-gradient(90deg,{bad} 0 6px,"
                           f"transparent 6px 12px)" if one_sided else f"background:{ok}")
                with ui.column().classes("items-center gap-0 px-3 py-2 rounded-lg") \
                        .style(f"background:{theme.SURFACE_2};border:1px solid "
                               + (f"{bad}66" if one_sided else f"{ok}66")):
                    ui.icon("cable").style(f"color:{bad if one_sided else ok}")
                    ui.label(f.harness_without or f.harness_with) \
                        .classes("text-xs font-semibold")

        # ------------- audit + signoff (unchanged behavior) ---------------
        def audit_tab(r) -> None:
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

        def signoff(r, baseline) -> None:
            blocking = r.blocking_open(baseline)
            with ui.row().classes("items-center gap-3 flex-wrap"):
                who = ui.input("Systems Engineer", value=state["engineer"]) \
                    .classes("w-56").props("dense")
                who.on_value_change(lambda e: state.update(engineer=e.value))
                ui.button("Sign off this run", icon="task_alt",
                          on_click=lambda: do_signoff()) \
                    .props("unelevated").set_enabled(not blocking)
                if blocking:
                    c.chip("high", f"{len(blocking)} open Blocker/High first")
                c.download_button("Circuit_Health_Report.xlsx",
                                  lambda: health.render_report(
                                      state["result"],
                                      health.load_baseline(BASELINE_PATH)))

        # ------------- actions --------------------------------------------
        def refresh_all() -> None:
            header.refresh()
            workbench.refresh()

        def dispose(f, verdict: str, reason: str) -> None:
            baseline = health.load_baseline(BASELINE_PATH)
            health.disposition(baseline, f, verdict, reason or "",
                               state["engineer"])
            health.save_baseline(BASELINE_PATH, baseline)
            state["selected"] = None
            ui.notify(f"{f.circuit or f.inline}: {verdict}", type="positive")
            refresh_all()

        def do_signoff() -> None:
            baseline = health.load_baseline(BASELINE_PATH)
            health.sign_off(baseline, state["engineer"])
            health.save_baseline(BASELINE_PATH, baseline)
            ui.notify("Run signed off and recorded", type="positive")

        def select(f) -> None:
            state["selected"] = f.fingerprint
            workbench.refresh()

        def toggle_sev(sev: str) -> None:
            s = state["filters"]["severities"]
            s.symmetric_difference_update({sev})
            workbench.refresh()

        def set_query(value: str) -> None:
            state["filters"]["query"] = value or ""
            workbench.refresh()

        def set_pair(e) -> None:
            data = getattr(e, "data", None)
            pair = data.get("pair") if isinstance(data, dict) else None
            if pair:
                state["filters"]["pair"] = tuple(pair)
                workbench.refresh()

        def clear_pair() -> None:
            state["filters"]["pair"] = None
            workbench.refresh()

        def set_kind(e) -> None:
            name = getattr(e, "name", None)
            for kind, label in KIND_LABEL.items():
                if label == name:
                    state["filters"]["kind"] = kind
                    workbench.refresh()
                    return

        def clear_kind() -> None:
            state["filters"]["kind"] = None
            workbench.refresh()

        def set_circuit(e) -> None:
            name = getattr(e, "name", None)
            if name:
                state["filters"]["query"] = str(name)
                workbench.refresh()

        workbench()

        async def run_check() -> None:
            if not (state["summary"] and state["cx"]):
                ui.notify("Load the Circuit Summary and complexity files first",
                          type="warning")
                return

            def work():
                name, blob = state["summary"]
                harnesses, ends = read_circuit_summary(blob, name)
                complexity, rejected = {}, []
                for cx_name, cx_blob in state["cx"].items():
                    try:
                        cx = read_complexity(cx_blob, cx_name)
                        cx.complexity_file = cx_name
                        if cx.def_id in harnesses:
                            complexity[cx.def_id] = cx
                        else:
                            rejected.append(f"{cx_name} (DEF id {cx.def_id} "
                                            "not in the summary)")
                    except Exception as exc:
                        rejected.append(f"{cx_name}: {exc}")
                pairs, unmated = resolve(ends, set(harnesses))
                return health.analyze(harnesses, ends, complexity,
                                      pairs, unmated), rejected

            out = await c.run_engine(work, running="Analyzing every inline, "
                                                   "cavity, and option window…",
                                     done="Health check complete")
            if out is not None:
                state["result"], state["rejected"] = out
                refresh_all()
