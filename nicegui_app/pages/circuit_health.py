"""Circuit Health — the SE review workbench.

Archetype B (workbench): a sticky step bar names the three stages — Inputs,
Review, Sign-off — from the first paint and carries their state; the KPI
strip under it burns down as findings are dispositioned; the header says who
saved the baseline last.

In the review the charts are the filters: a harness-pair matrix, a kind
breakdown, and a circuit-impact chart all scope the queue when clicked, and
every one of them mirrors a chip beside the list so the same scope is
reachable from the keyboard. A master-detail split keeps the list compact
and draws each finding — the two harnesses, the inline between them, and
which builds carry the wire versus not — so evidence is read visually, not
parsed out of expressions. Dispositions live in the detail pane.

Absorbs Inline Continuity (the audit tab); the engine is splice.inline.health
unchanged.
"""

from __future__ import annotations

import os
from datetime import datetime
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
              "route_window_gap": "Route gap",
              "integrity": "Applicability mismatch"}
STEPS = ("Inputs", "Review", "Sign-off")
CLEARED_LABELS = {"inline": "Inline", "cavity": "Cavity", "window": "Window",
                  "reason": "Proof"}
DONE_LABELS = {"verdict": "Disposition", "kind": "Kind", "inline": "Inline",
               "circuit": "Circuit(s)", "by": "By", "date": "Date",
               "reason": "Reason"}


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
    """The option dict; ``c.echart`` fills the axis, text and tooltip
    tokens, so only what differs from the theme is typed here."""
    m = matrix_data(open_findings)
    labels = theme.axis_style()["axisLabel"]
    axis = {"type": "category", "data": m["names"],
            "axisLabel": {**labels, "rotate": 35},
            "splitLine": {"show": False}}
    return {
        "grid": {"left": 110, "right": 12, "top": 8, "bottom": 70},
        "xAxis": axis,
        "yAxis": {**axis, "axisLabel": dict(labels)},
        "series": [{"type": "heatmap", "data": m["data"],
                    "label": {"show": True, "color": theme.CANVAS,
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
        "grid": {"left": 150, "right": 24, "top": 8, "bottom": 24},
        "xAxis": {"type": "value"},
        "yAxis": {"type": "category", "data": labels},
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
        "grid": {"left": 70, "right": 24, "top": 8, "bottom": 24},
        "xAxis": {"type": "value"},
        "yAxis": {"type": "category",
                  "data": [k for k, _ in reversed(ranked)],
                  "axisLabel": {**theme.axis_style()["axisLabel"],
                                "fontFamily": theme.MONO}},
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
    state: dict = {
        "summary": None, "cx": {}, "result": None,
        #: what the run had to say — notes under the action, not toasts
        "run_notes": [],
        "filters": {"severities": set(), "kind": None, "pair": None, "query": ""},
        "selected": None, "engineer": c.who(),
        #: which review tab is open, so a refresh does not snap back
        "tab": "open",
        #: the Inputs card shows its upload rows; it folds once a result exists
        "editing": True, "preloaded": False,
        #: who signed this run, once someone has
        "signed": "",
    }

    auto_dir = os.getenv("SPLICE_HEALTH_AUTOLOAD")
    if auto_dir and Path(auto_dir).is_dir():
        d = Path(auto_dir)
        s = next(iter(d.glob("Circuit Summary*.xlsx")), None)
        if s is not None:
            state["summary"] = (s.name, s.read_bytes())
        for f in sorted(d.glob("*.xls[mM]")):
            state["cx"][f.name] = f.read_bytes()
        state["preloaded"] = bool(state["summary"] or state["cx"])

    with c.frame("Circuit Health",
                 "Missing circuits across inlines — cavity checks, option-window "
                 "coverage, route gaps — reviewed, dispositioned, signed off."):
        envelope = c.envelope("")
        c.step_bar(*STEPS)

        # ------------------------------------------------ the baseline envelope
        def baseline() -> dict:
            return health.load_baseline(BASELINE_PATH)

        def show_envelope(b: dict | None = None) -> None:
            b = baseline() if b is None else b
            if b.get("saved_at"):
                envelope.set_text(f"Saved by {b.get('saved_by') or 'unknown'} · "
                                  f"{b['saved_at']}")
            else:
                envelope.set_text("Nothing saved yet")

        def save(b: dict) -> None:
            """Every save carries who and when, so the header can say so."""
            b["saved_by"] = c.who() or state["engineer"] or ""
            b["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            health.save_baseline(BASELINE_PATH, b)
            show_envelope(b)

        # ------------------------------------------------------ step states
        def sync() -> None:
            """Step states, the KPI strip and the envelope follow the state;
            nothing sets them by hand."""
            r = state["result"]
            if r is None:
                loaded = len(state["cx"]) + (1 if state["summary"] else 0)
                c.set_step("Inputs", "current", f"{loaded} file(s)" if loaded else "")
                c.set_step("Review", "waiting", "")
                c.set_step("Sign-off", "waiting", "")
            else:
                b = baseline()
                open_f = r.open_findings(b)
                blocking = r.blocking_open(b)
                c.set_step("Inputs", "done",
                           f"{len(r.inputs.rows)} harness(es) · {len(state['cx'])} file(s)")
                c.set_step("Review", "done" if not open_f else "current",
                           f"{len(open_f)} open")
                if state["signed"]:
                    c.set_step("Sign-off", "done", f"signed by {state['signed']}")
                elif blocking:
                    c.set_step("Sign-off", "blocked", f"{len(blocking)} Blocker/High open")
                else:
                    c.set_step("Sign-off", "current", "ready")
            kpi_view.refresh()
            show_envelope()

        def refresh_all() -> None:
            inputs_view.refresh()
            workbench.refresh()
            signoff_view.refresh()
            sync()

        def refresh_queue() -> None:
            """Only the filter chips and the list — the charts are drawn
            from the open findings, which a filter does not change."""
            filters_view.refresh()
            queue_view.refresh()

        # --------------------------------------------------------- KPI strip
        @ui.refreshable
        def kpi_view() -> None:
            r = state["result"]
            if not r:
                return
            b = baseline()
            open_f = r.open_findings(b)
            n_blocker = sum(1 for f in open_f if f.severity == "Blocker")
            n_high = sum(1 for f in open_f if f.severity == "High")
            n_review = sum(1 for f in open_f if f.severity == "Review")
            done = len(r.findings) - len(open_f)
            with c.kpi_strip():
                c.kpi(n_blocker, "Blockers open", "blocker" if n_blocker else "ok")
                c.kpi(n_high, "High open", "high" if n_high else None)
                c.kpi(n_review, "Review open", "review" if n_review else None)
                c.kpi(done, "Dispositioned", "ok" if done else None)
                c.kpi(len(r.cleared), "Auto-cleared", "info")
            segments = progress_segments(r, b)
            if segments:
                with ui.row().classes("w-full h-2 rounded-full overflow-hidden gap-0"):
                    for color, fraction, _ in segments:
                        ui.element("div").style(
                            f"background:{color};width:{fraction * 100:.2f}%")
                ui.label(" · ".join(s[2] for s in segments)).classes("sx-caption")

        # ------------------------------------------------------------- guide
        def guide() -> None:
            with ui.expansion("How this tool works — SE review guide", icon="school") \
                    .classes("w-full").props("dense"):
                for title, lines in health.REVIEWER_GUIDE:
                    ui.label(title).classes("text-sm font-bold mt-2")
                    for line in lines:
                        ui.label(f"• {line}").classes("text-xs sx-muted")
                ui.label("The exported report carries this guide as its Read Me "
                         "sheet, so reviewers without the app see it too.") \
                    .classes("text-xs sx-muted mt-2 italic")

        # ------------------------------------------------------------ inputs
        def missing() -> list[str]:
            out = []
            if not state["summary"]:
                out.append("the Circuit Summary")
            if not state["cx"]:
                out.append("at least one complexity file")
            return out

        def loaded_line() -> str:
            name = state["summary"][0] if state["summary"] else "no Circuit Summary"
            return f"{name} + {len(state['cx'])} complexity file(s)"

        @ui.refreshable
        def inputs_view() -> None:
            if state["result"] is not None and not state["editing"]:
                with ui.row().classes("items-center gap-3 flex-wrap"):
                    ui.label(f"Loaded: {loaded_line()}").classes("text-sm")
                    ui.button("Change files", icon="edit",
                              on_click=lambda: (state.update(editing=True),
                                                inputs_view.refresh())) \
                        .props("outline dense no-caps")
                for kind, text in state["run_notes"]:
                    c.note(kind, text)
                return
            with ui.row().classes("w-full gap-4 flex-wrap"):
                c.upload_row("Circuit Summary (.xlsx)",
                             lambda n, b: (state.update(summary=(n, b)), sync()),
                             accept=".xlsx")
                c.upload_row("Complexity files (.xlsm)",
                             lambda n, b: (state["cx"].__setitem__(n, b), sync()),
                             accept=".xlsm,.xlsx", multiple=True)
            if state["preloaded"]:
                c.note("info", f"Preloaded: {loaded_line()}")
            c.action("Run health check", run_check, needs=missing)
            for kind, text in state["run_notes"]:
                c.note(kind, text)

        # ------------------------------------------------------------ review
        @ui.refreshable
        def workbench() -> None:
            r = state["result"]
            if not r:
                c.empty("Run the health check to open the review.",
                        icon="monitor_heart")
                return
            b = baseline()
            dispositions = b.get("dispositions", {})
            open_f = r.open_findings(b)
            done_f = [f for f in r.findings if f.fingerprint in dispositions]

            with ui.tabs(value=state["tab"],
                         on_change=lambda e: state.update(tab=e.value)) \
                    .props("dense align=left") as tabs:
                ui.tab("open", label=f"Open ({len(open_f)})")
                ui.tab("done", label=f"Dispositioned ({len(done_f)})")
                ui.tab("cleared", label=f"Auto-cleared ({len(r.cleared)})")
                ui.tab("audit", label="Continuity audit")
            with ui.tab_panels(tabs, value=state["tab"]).classes("w-full"):
                with ui.tab_panel("open").classes("p-0 pt-2"):
                    work_tab(open_f, dispositions)
                with ui.tab_panel("done").classes("p-0 pt-2"):
                    done_tab(done_f, dispositions)
                with ui.tab_panel("cleared").classes("p-0 pt-2"):
                    cleared_tab(r)
                with ui.tab_panel("audit").classes("p-0 pt-2"):
                    audit_tab(r)

        def work_tab(open_f, dispositions) -> None:
            if not open_f:
                c.empty("Every finding is dispositioned — nothing is open.",
                        icon="task_alt")
                return
            with ui.row().classes("w-full gap-3 flex-wrap"):
                with ui.card().classes("sx-card flex-1 min-w-[22rem]"):
                    ui.label("Where — open findings per harness pair").classes("sx-eyebrow")
                    ui.label("Click a cell to scope the queue; the diagonal is "
                             "within-harness route gaps.").classes("sx-caption")
                    c.echart(matrix_options(open_f), on_point_click=set_pair) \
                        .classes("w-full h-64")
                    with ui.row().classes("gap-3"):
                        for sev in SEV_ORDER:
                            c.chip(SEV_KIND[sev], sev)
                with ui.column().classes("flex-1 min-w-[20rem] gap-3"):
                    with ui.card().classes("sx-card w-full"):
                        ui.label("What kind").classes("sx-eyebrow")
                        c.echart(kind_bar_options(open_f), on_point_click=set_kind) \
                            .classes("w-full h-28")
                    with ui.card().classes("sx-card w-full"):
                        ui.label("Top circuits by affected builds — click to search") \
                            .classes("sx-eyebrow")
                        c.echart(circuit_bar_options(open_f), on_point_click=set_circuit) \
                            .classes("w-full h-40")
            filters_view(open_f)
            queue_view(open_f, dispositions)

        @ui.refreshable
        def filters_view(open_f) -> None:
            """The chips are the keyboard path; every chart click lands on
            one of them."""
            filters = state["filters"]
            kinds = [k for k in KIND_LABEL if any(f.kind == k for f in open_f)]
            pairs: dict[tuple, int] = {}
            for f in open_f:
                pairs[pair_key(f)] = pairs.get(pair_key(f), 0) + 1
            active = bool(filters["severities"] or filters["kind"]
                          or filters["pair"] or filters["query"])
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                ui.label("Severity").classes("sx-eyebrow")
                for sev in SEV_ORDER:
                    c.toggle_chip(sev, sev in filters["severities"],
                                  lambda s=sev: toggle_sev(s),
                                  sum(1 for f in open_f if f.severity == sev))
                ui.label("Kind").classes("sx-eyebrow ml-2")
                for kind in kinds:
                    c.toggle_chip(KIND_LABEL[kind], filters["kind"] == kind,
                                  lambda k=kind: toggle_kind(k),
                                  sum(1 for f in open_f if f.kind == kind))
                search = ui.input("Search circuits or connectors",
                                  value=filters["query"]) \
                    .props("dense clearable").classes("w-64 ml-2")
                search.on_value_change(lambda e: set_query(e.value))
                if active:
                    ui.button("Clear filters", icon="filter_alt_off",
                              on_click=clear_filters).props("flat dense no-caps")
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                ui.label("Pair").classes("sx-eyebrow")
                for pair, n in sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0])):
                    c.toggle_chip(f"{pair[0]} ↔ {pair[1]}", filters["pair"] == pair,
                                  lambda p=pair: toggle_pair(p), n)

        @ui.refreshable
        def queue_view(open_f, dispositions) -> None:
            visible = filter_findings(open_f, state["filters"])
            # something is always selected while there is a list to select from
            if visible and state["selected"] not in {f.fingerprint for f in visible}:
                state["selected"] = visible[0].fingerprint
            ui.label(f"{len(visible)} of {len(open_f)} open findings").classes("sx-caption")
            with ui.splitter(value=55).classes("w-full") as splitter:
                with splitter.before:
                    with ui.column().classes("w-full gap-1 pr-3 max-h-[34rem] "
                                             "overflow-y-auto"):
                        if not visible:
                            c.empty("No finding matches these filters.",
                                    icon="filter_alt")
                        for f in visible:
                            master_row(f)
                with splitter.after:
                    with ui.column().classes("w-full pl-3"):
                        detail(visible, dispositions)

        def master_row(f) -> None:
            active = state["selected"] == f.fingerprint
            row = ui.button(on_click=lambda _e, fp=f.fingerprint: select(fp)) \
                .props(f'flat no-caps align=left aria-pressed="{"true" if active else "false"}"') \
                .classes("rounded px-2 py-1.5 w-full normal-case") \
                .style(f"background:{theme.wash(theme.BRAND)}" if active
                       else f"background:{theme.SURFACE_2}")
            with row:
                with ui.row().classes("items-center gap-2 no-wrap w-full"):
                    c.chip(SEV_KIND[f.severity], f.severity)
                    ui.label(f.circuit or "—").classes(
                        "text-sm font-semibold sx-mono truncate max-w-[12rem]")
                    ui.label(f.inline).classes("text-sm sx-muted truncate flex-1 text-left")
                    if f.builds_without:
                        ui.label(f"{len(f.builds_without)} builds") \
                            .classes("text-xs shrink-0") \
                            .style(f"color:{theme.STATUS['blocker']}")

        # ------------------------------------------------------ detail pane
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

            if f.window_display:
                ui.label("Option window with no wire (minimized)") \
                    .classes("sx-eyebrow mt-1")
                ui.label(f.window_display).classes(
                    "text-sm sx-mono p-2 rounded w-full") \
                    .style(f"background:{theme.CANVAS}")
                if f.window_short and f.window_short != f.window:
                    with ui.expansion("raw expression").classes("w-full") \
                            .props("dense"):
                        ui.label(f.window).classes("text-xs sx-mono break-all")
            ui.label(f.detail).classes("text-sm sx-muted")

            with ui.row().classes("w-full gap-4 flex-wrap mt-1"):
                if f.builds_with:
                    _builds(f"Has the wire — {f.harness_with}", f.builds_with,
                            theme.STATUS["ok"])
                if f.builds_without:
                    _builds(f"No wire — {f.harness_without}", f.builds_without,
                            theme.STATUS["blocker"])

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
                              on_click=lambda _e, v=verdict: dispose(f, v, reason.value)) \
                        .props("outline dense no-caps")

        def _builds(title: str, part_numbers, color: str) -> None:
            with ui.column().classes("gap-1"):
                ui.label(title).classes("text-xs font-bold").style(f"color:{color}")
                with ui.row().classes("gap-1 flex-wrap max-w-xs"):
                    for pn in part_numbers:
                        ui.label(pn).classes("text-xs sx-mono px-1.5 py-0.5 rounded") \
                            .style(f"background:{theme.wash(color)};color:{color}")

        def _diagram(f) -> None:
            """Two harnesses and the inline between them, drawn — or, for a
            route gap, ONE harness and its crossings (a route gap lives within
            a single harness; drawing it as A ↔ A misread as an inline)."""
            ok, bad = theme.STATUS["ok"], theme.STATUS["blocker"]
            if f.kind == "route_window_gap":
                with ui.row().classes("items-center w-full gap-3 my-2 flex-wrap"):
                    with ui.column().classes("items-center gap-0 px-3 py-2 rounded-lg") \
                            .style(f"background:{theme.SURFACE_2};"
                                   f"border:1px solid {theme.wash(theme.BRAND, '66')}"):
                        ui.icon("cable").style(f"color:{theme.BRAND}")
                        ui.label(f.harness_with).classes("text-xs font-semibold")
                        ui.label("one harness").classes("text-xs sx-muted")
                    with ui.column().classes("gap-1"):
                        for crossing in f.crossings:
                            with ui.row().classes("items-center gap-1"):
                                ui.icon("check_circle").classes("text-sm") \
                                    .style(f"color:{ok}")
                                ui.label(f"{crossing} — has {f.circuit} variants") \
                                    .classes("text-xs sx-mono")
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("cancel").classes("text-sm").style(f"color:{bad}")
                            ui.label(f"{f.inline} — no variant in this window") \
                                .classes("text-xs sx-mono font-bold") \
                                .style(f"color:{bad}")
                return
            one_sided = f.kind == "one_sided_window"
            with ui.row().classes("items-center w-full gap-0 my-2"):
                with ui.column().classes("items-center gap-0 px-3 py-2 rounded-lg") \
                        .style(f"background:{theme.SURFACE_2};"
                               f"border:1px solid {theme.wash(ok, '66')}"):
                    ui.icon("cable").style(f"color:{ok}")
                    ui.label(f.harness_with).classes("text-xs font-semibold")
                ui.element("div").classes("flex-1 h-0.5") \
                    .style(f"background:{ok}")
                with ui.column().classes("items-center gap-0 px-2"):
                    ui.icon("settings_input_component").classes("text-lg") \
                        .style(f"color:{theme.BRAND}")
                    ui.label(f.inline.split(' ')[0] if one_sided else f.inline) \
                        .classes("text-xs sx-mono sx-muted")
                    if f.cavity:
                        ui.label(f"cav {f.cavity}").classes("text-xs sx-muted")
                ui.element("div").classes("flex-1 h-0.5") \
                    .style(f"background:repeating-linear-gradient(90deg,{bad} 0 6px,"
                           f"transparent 6px 12px)" if one_sided else f"background:{ok}")
                far = bad if one_sided else ok
                with ui.column().classes("items-center gap-0 px-3 py-2 rounded-lg") \
                        .style(f"background:{theme.SURFACE_2};"
                               f"border:1px solid {theme.wash(far, '66')}"):
                    ui.icon("cable").style(f"color:{far}")
                    ui.label(f.harness_without or f.harness_with) \
                        .classes("text-xs font-semibold")

        # ------------------------------------------------------- other tabs
        def done_tab(done_f, dispositions) -> None:
            if not done_f:
                c.empty("Nothing dispositioned yet.", icon="rule")
                return
            rows = []
            for f in done_f:
                d = dispositions[f.fingerprint]
                rows.append({"verdict": d.get("verdict", ""),
                             "kind": KIND_LABEL.get(f.kind, f.kind),
                             "inline": f.inline, "circuit": f.circuit,
                             "by": d.get("by", ""), "date": d.get("date", ""),
                             "reason": d.get("reason", "")})
            c.frame_table(rows, labels=DONE_LABELS, mono=("inline", "circuit"))

        def cleared_tab(r) -> None:
            if not r.cleared:
                c.empty("Nothing was auto-cleared in this run.", icon="verified")
                return
            c.frame_table([{"inline": p.inline, "cavity": p.cavity,
                            "window": p.window, "reason": p.detail}
                           for p in r.cleared],
                          cap=300, labels=CLEARED_LABELS, mono=("inline", "window"))

        def audit_tab(r) -> None:
            from splice.inline import report as inline_report
            study = r.study
            if study is None:
                c.empty("Run the health check to build the audit.")
                return
            counts = study.verdict_counts()
            with c.kpi_strip():
                c.kpi(study.cavities_checked, "Cavities checked")
                c.kpi(counts.get("Continuous", 0), "Continuous", "ok")
                c.kpi(len(study.review), "Need review",
                      "review" if study.review else None)
                c.kpi(len(study.pairs), "Inline pairs")
            if r.gaps:
                with ui.expansion(f"Input readiness notes ({len(r.gaps)})") \
                        .classes("w-full").props("dense"):
                    audit_table(inline_report.gaps_frame(r.gaps))
            for title, frame in [
                    ("Cavities needing review", inline_report.review_frame(study)),
                    ("Marked differences inside continuous cavities",
                     inline_report.marked_frame(study)),
                    ("Every cavity", inline_report.all_frame(study)),
                    ("Every circuit (one row per wire)",
                     inline_report.options_frame(study))]:
                with ui.expansion(f"{title} ({len(frame)})").classes("w-full") \
                        .props("dense"):
                    audit_table(frame)
            c.download(c.export_name("Inline_Continuity_Findings"),
                       lambda: inline_report.build_workbook(state["result"].study,
                                                            state["result"].gaps))

        def audit_table(df) -> None:
            if df is None or df.empty:
                c.empty("Nothing in this view.", icon="table_rows")
                return
            view = df.astype(str)
            # the frames already carry their headings; keep them verbatim
            c.frame_table(view, cap=500, labels={col: col for col in view.columns})

        # ---------------------------------------------------------- sign-off
        @ui.refreshable
        def signoff_view() -> None:
            r = state["result"]
            if not r:
                c.empty("Sign-off opens once a health check has run and every "
                        "Blocker and High is dispositioned.", icon="task_alt")
                return
            state["engineer"] = state["engineer"] or c.who()
            with ui.row().classes("items-start gap-3 flex-wrap"):
                who = ui.input("Systems Engineer", value=state["engineer"]) \
                    .classes("w-56").props("dense")
                who.on_value_change(lambda e: state.update(engineer=e.value))
                c.action("Sign off this run", do_signoff, icon="task_alt",
                         needs=lambda: (
                             [f"{len(r.blocking_open(baseline()))} open "
                              "Blocker/High dispositioned"]
                             if r.blocking_open(baseline()) else []))
                c.download(c.export_name("Circuit_Health_Report"),
                           lambda: health.render_report(state["result"], baseline()))
            if state["signed"]:
                c.note("ok", f"Signed off by {state['signed']} — recorded in the baseline")

        # ----------------------------------------------------------- actions
        def dispose(f, verdict: str, reason: str) -> None:
            r = state["result"]
            b = baseline()
            before = filter_findings(r.open_findings(b), state["filters"])
            index = next((i for i, x in enumerate(before)
                          if x.fingerprint == f.fingerprint), 0)
            health.disposition(b, f, verdict, reason or "", state["engineer"])
            save(b)
            # keep the place in the queue: the next finding in the list takes
            # the selection, never nothing
            after = filter_findings(r.open_findings(b), state["filters"])
            if after and f.fingerprint not in {x.fingerprint for x in after}:
                state["selected"] = after[min(index, len(after) - 1)].fingerprint
            ui.notify(f"{f.circuit or f.inline}: {verdict}", type="positive")
            refresh_all()

        def do_signoff() -> None:
            b = baseline()
            health.sign_off(b, state["engineer"])
            save(b)
            state["signed"] = state["engineer"] or c.who() or "unnamed"
            ui.notify("Run signed off and recorded", type="positive")
            refresh_all()

        def select(fingerprint: str) -> None:
            state["selected"] = fingerprint
            queue_view.refresh()

        def toggle_sev(sev: str) -> None:
            state["filters"]["severities"].symmetric_difference_update({sev})
            refresh_queue()

        def toggle_kind(kind: str) -> None:
            filters = state["filters"]
            filters["kind"] = None if filters["kind"] == kind else kind
            refresh_queue()

        def toggle_pair(pair: tuple) -> None:
            filters = state["filters"]
            filters["pair"] = None if filters["pair"] == pair else pair
            refresh_queue()

        def set_query(value: str) -> None:
            state["filters"]["query"] = value or ""
            queue_view.refresh()   # not the chips: the search field keeps focus

        def clear_filters() -> None:
            state["filters"] = {"severities": set(), "kind": None,
                                "pair": None, "query": ""}
            refresh_queue()

        def set_pair(e) -> None:
            data = getattr(e, "data", None)
            pair = data.get("pair") if isinstance(data, dict) else None
            if pair:
                state["filters"]["pair"] = tuple(pair)
                refresh_queue()

        def set_kind(e) -> None:
            name = getattr(e, "name", None)
            for kind, label in KIND_LABEL.items():
                if label == name:
                    state["filters"]["kind"] = kind
                    refresh_queue()
                    return

        def set_circuit(e) -> None:
            name = getattr(e, "name", None)
            if name:
                state["filters"]["query"] = str(name)
                refresh_queue()

        async def run_check() -> None:
            if not (state["summary"] and state["cx"]):
                return   # the action is gated; this is only a guard

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
                    except Exception as exc:  # noqa: BLE001 — an unreadable file is reported, not fatal
                        rejected.append(f"{cx_name}: {exc}")
                pairs, unmated = resolve(ends, set(harnesses))
                return health.analyze(harnesses, ends, complexity,
                                      pairs, unmated), rejected

            out = await c.run_engine(work, running="Analyzing every inline, "
                                                   "cavity, and option window…",
                                     done="Health check complete")
            if out is None:
                return
            result, rejected = out
            state.update(result=result, selected=None, editing=False,
                         signed="", tab="open")
            # One toast per action (the runner's). Everything else the run
            # has to say stays on the page, under the action.
            notes = [("high", f"Not used: {problem}") for problem in rejected]
            if result.inputs.missing_complexity:
                notes.append(("high", "Missing complexity: "
                              + ", ".join(result.inputs.missing_complexity)))
            if result.inputs.skew_days > 30:
                notes.append(("review", f"Revision skew {result.inputs.skew_days} "
                                        f"days — {result.inputs.skew_pair}"))
            notes.append(("info", f"{len(result.inputs.rows)} harness(es) matched · "
                                  f"{result.cavities_checked:,} cavities checked · "
                                  f"{len(result.findings)} finding(s)"))
            state["run_notes"] = notes
            refresh_all()

        # ------------------------------------------------------------ layout
        kpi_view()
        guide()
        with c.section("Inputs",
                       "Circuit Summary + one Harness Complexity per harness — "
                       "matched by the DEF id inside each file.", step="Inputs"):
            inputs_view()
        with c.section("Review",
                       "The charts are the filters: click a matrix cell, a kind, "
                       "or a circuit to scope the queue — or press the chips.",
                       step="Review"):
            workbench()
        with c.section("Sign-off",
                       "Possible once no Blocker or High is open; the report "
                       "carries every disposition as the audit trail.",
                       step="Sign-off"):
            signoff_view()
        sync()
