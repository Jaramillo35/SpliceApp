"""Circuit Applicability workbench.

Three stages, in order:

1. **Load** the DTx and the individual complexity files.
2. **Map** each DTx harness family to its complexity file(s) — a family may
   take several, since one DTx family is often carried by more than one
   physical harness. Exact name matches connect themselves; the rest are added
   from the dropdown or by clicking a suggestion. The analysis runs ONLY where
   a mapping exists, because attributing one harness's builds to another
   family produces a confident wrong answer.
3. **Review** circuits, connectors (CNUM) and sales-code gaps per family.
"""

from __future__ import annotations


from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme

ROW_H = 34          # px; every cell in a row shares it so the lines align
GRID = "grid-template-columns: 1.1fr 64px 1.25fr 1.5fr"
GREEN = "#3fb950"
RED = "#f85149"

VERDICT_KIND = {
    "unconditional": "ok", "all builds": "ok", "variant": "info",
    "never built": "blocker", "no complexity": "review",
}


def _line(matched: bool) -> str:
    """The connector between a family and its complexity file."""
    if matched:
        return (f'<svg width="100%" height="{ROW_H}">'
                f'<line x1="0" y1="{ROW_H//2}" x2="100%" y2="{ROW_H//2}" '
                f'stroke="{GREEN}" stroke-width="2"/>'
                f'<circle cx="6" cy="{ROW_H//2}" r="3" fill="{GREEN}"/>'
                f'<circle cx="calc(100% - 6px)" cy="{ROW_H//2}" r="3" fill="{GREEN}"/>'
                f'</svg>')
    return (f'<svg width="100%" height="{ROW_H}">'
            f'<line x1="0" y1="{ROW_H//2}" x2="100%" y2="{ROW_H//2}" '
            f'stroke="{RED}" stroke-width="2" stroke-dasharray="6,5"/>'
            f'<circle cx="6" cy="{ROW_H//2}" r="3" fill="none" stroke="{RED}" '
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
            "connected to at least one complexity file — a **green solid "
            "line**. A **red dotted line** means nothing is connected and that "
            "family is skipped. Add harnesses from the dropdown (files with "
            "**no likely family** are listed first, since nothing else will "
            "surface them) or click a suggestion on the right; ✕ removes one. "
            "A family mapped to several harnesses is resolved against each "
            "separately, so you can see a circuit that is fine on one and "
            "never built on another.\n\n"
            "**Review filters** combine: *Findings*, *Needs review* (a finding "
            "or a circuit resting on an untracked code), any verdict, and a "
            "single condition — useful for seeing every circuit that shares "
            "one sales-code expression. Tick a row to add it to the "
            "**Complexity Cleanup Notes** column of the exported workbook.\n\n"
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
    from splice.dtxcircuits import report as report_mod
    from splice.dtxcircuits import chart as chart_mod
    from splice.dtxcircuits import integrity, quality as quality_mod, store
    from splice.dtxcircuits.complexity import read_harness_file

    state: dict = {
        "dtx": None, "uploads": {},
        "rows": [], "dtx_meta": None, "families": [],
        "harnesses": {},        # filename -> Harness
        "metas": {},            # filename -> ComplexityMeta
        "mapping": {},          # family -> [filename, ...] (a family may take
                                #            several harnesses)
        "corr": None, "entries": [], "selected": None, "only_open": False,
        #: rows ticked for the Complexity Cleanup Notes column, by item key
        "cleanup": {},
        "filters": {"findings": False, "needs_review": False,
                    "verdicts": set(), "condition": None},
        #: which review tab is open, so a refresh does not snap back
        "tab": "circuits",
        #: measured on load and again after analysis
        "quality": None,
        #: one circuit chart per family x harness, built with the analysis
        "charts": [],
        #: which chart is expanded, so a refresh does not collapse it
        "chart_open": None,
        #: keys the SE explicitly unticked — never auto-selected again
        "dismissed": set(),
        #: malformed sales-code expressions, and the repairs confirmed for them
        "issues": [], "fixes": {},
        "issue_filter": {"unresolved_only": True, "kinds": set()},
        #: what the previous session left behind
        "stored": store.load(),
    }
    state["cleanup"] = store.restore_cleanup(state["stored"].get("cleanup", {}))
    state["fixes"] = dict(state["stored"].get("fixes", {}))
    state["dismissed"] = set(state["stored"].get("dismissed", []))

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

        # ---------------------------------------------------- sales-code data
        def _open_issues() -> list:
            return [i for i in state["issues"]
                    if i.expression not in state["fixes"]]

        def _resolve(expression: str, replacement: str) -> None:
            state["fixes"][expression] = replacement
            state["entries"] = state["charts"] = []   # the analysis is now stale
            _persist()
            _measure()
            chart_view.refresh()
            integrity_view.refresh()
            results_view.refresh()

        def _resolve_manual(expression: str, typed: str) -> None:
            """A hand-typed repair is checked before it is stored: an unchecked
            one can be malformed in its own right, and would then be applied to
            every circuit using that expression."""
            blocking, warnings = integrity.validate_replacement(expression, typed)
            if blocking:
                ui.notify(" ".join(blocking), type="negative", multi_line=True,
                          close_button=True)
                return
            for warning in warnings:
                ui.notify(warning, type="warning", multi_line=True,
                          close_button=True)
            _resolve(expression, typed.strip())

        def _unresolve(expression: str) -> None:
            state["fixes"].pop(expression, None)
            state["entries"] = state["charts"] = []
            _persist()
            _measure()
            chart_view.refresh()
            integrity_view.refresh()
            results_view.refresh()

        @ui.refreshable
        def integrity_view() -> None:
            if not state["issues"]:
                if state["rows"]:
                    with c.card("2 · Sales-code integrity"):
                        c.chip("ok", "Every sales-code expression in this DTx "
                                     "parses — nothing to fix")
                return
            f = state["issue_filter"]
            issues = state["issues"]
            open_issues = _open_issues()
            kinds = sorted({i.kind for i in issues})
            shown = [i for i in issues
                     if not (f["unresolved_only"] and i.expression in state["fixes"])
                     and (not f["kinds"] or i.kind in f["kinds"])]

            with c.card("2 · Sales-code integrity",
                        "Checked before anything is resolved: a malformed "
                        "expression is false for every configuration, so its "
                        "circuits would read as 'never built' and look like "
                        "real defects."):
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    c.chip("blocker" if open_issues else "ok",
                           f"{len(open_issues)} unresolved")
                    if len(issues) - len(open_issues):
                        c.chip("ok", f"{len(issues) - len(open_issues)} resolved "
                                     "(untick 'Unresolved only' to review)")
                    ui.label("FILTER").classes(
                        "text-[10px] font-bold tracking-widest sx-muted ml-2")
                    _filter_chip("Unresolved only", f["unresolved_only"],
                                 lambda: (f.__setitem__("unresolved_only",
                                                        not f["unresolved_only"]),
                                          integrity_view.refresh()),
                                 len(open_issues))
                    for kind in kinds:
                        _filter_chip(kind, kind in f["kinds"],
                                     lambda k=kind: (
                                         f["kinds"].symmetric_difference_update({k}),
                                         integrity_view.refresh()),
                                     sum(1 for i in issues if i.kind == kind))
                for issue in shown:
                    _issue_row(issue)
                if not shown:
                    c.empty("Nothing matches these filters.", icon="filter_alt")

        def _issue_row(issue) -> None:
            fixed = state["fixes"].get(issue.expression)
            with ui.element("div").classes("w-full rounded p-2 mt-1") \
                    .style(f"background:{theme.SURFACE_2};border:1px solid "
                           f"{(GREEN if fixed else RED)}55"):
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    c.chip("ok" if fixed else "blocker", issue.kind)
                    ui.label(issue.expression).classes(
                        "text-[12px] sx-mono font-semibold")
                    if fixed:
                        ui.icon("arrow_forward").classes("text-xs")
                        ui.label(fixed).classes("text-[12px] sx-mono font-semibold") \
                            .style(f"color:{GREEN}")
                    ui.label(f"{issue.rows} DTx row(s) · "
                             f"{len(issue.circuits)} circuit(s) · "
                             + ", ".join(issue.families[:3])) \
                        .classes("text-[10px] sx-muted")
                ui.label(issue.detail).classes("text-[10px] sx-muted")
                if fixed:
                    with ui.row().classes("gap-2 items-center"):
                        ui.button("Undo", icon="undo",
                                  on_click=lambda e=issue.expression: _unresolve(e)) \
                            .props("flat dense size=sm")
                    return
                with ui.row().classes("gap-2 items-center flex-wrap mt-1"):
                    for suggestion in issue.suggestions:
                        ui.button(suggestion.expression,
                                  icon="auto_fix_high",
                                  on_click=lambda e=issue.expression,
                                                  r=suggestion.expression:
                                      _resolve(e, r)) \
                            .props("outline dense no-caps") \
                            .tooltip(suggestion.reason)
                    manual = ui.input(placeholder="or type the correct expression") \
                        .props("dense outlined").classes("text-[11px] min-w-[14rem]")
                    ui.button("Use", icon="check",
                              on_click=lambda e=issue.expression, m=manual:
                                  _resolve_manual(e, m.value or "")) \
                        .props("flat dense size=sm")
                if not issue.suggestions:
                    ui.label("No automatic suggestion — this one needs a human "
                             "reading.").classes("text-[10px] sx-muted")

        integrity_view()

        # ------------------------------------------------------ data quality
        @ui.refreshable
        def quality_view() -> None:
            q = state["quality"]
            if q is None:
                return
            with c.card("5 · DTx data quality",
                        "What this export gets right, and what needs fixing at "
                        "source. The complexity files are built from the "
                        "customer's own information, so a mismatch here is "
                        "their data disagreeing with itself — which is what "
                        "makes it fair to send back."):
                with ui.row().classes("gap-2 flex-wrap items-center"):
                    c.chip("info", f"{q.program or '?'} · {q.phase or '?'}"
                                   + (f" · {q.report_date}" if q.report_date else ""))
                    c.chip("ok" if q.clean else "blocker",
                           "No findings" if q.clean
                           else f"{q.finding_total} finding(s) for the customer")

                _metric_row([
                    ("Rows", q.rows, "info"),
                    ("Circuits", q.circuits, "info"),
                    ("Connectors", q.connectors, "info"),
                    ("Families", q.families, "info"),
                    ("Conditioned", f"{q.conditioned_rows} ({q.conditioned_share:.0%})", "info"),
                    ("Sales codes", q.distinct_codes, "info"),
                ])

                ui.label("FINDINGS").classes(
                    "text-[10px] font-bold tracking-widest sx-muted mt-2")
                _metric_row([
                    ("Malformed expressions", q.malformed_expressions,
                     "blocker" if q.malformed_expressions else "ok"),
                    ("…rows affected", q.malformed_rows,
                     "review" if q.malformed_rows else "ok"),
                    ("Never-built circuits", q.never_built_circuits,
                     "blocker" if q.never_built_circuits else "ok"),
                    ("Never-built connectors", q.never_built_connectors,
                     "blocker" if q.never_built_connectors else "ok"),
                    ("Codes tracked nowhere", len(q.codes_not_tracked_anywhere),
                     "blocker" if q.codes_not_tracked_anywhere else "ok"),
                    ("Codes partly tracked", len(q.codes_partially_tracked),
                     "review" if q.codes_partially_tracked else "ok"),
                ])
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
                                 "where it is not.").classes("text-[10px] sx-muted")
                        ui.table(rows=[{
                            "code": x.code, "status": x.status, "rows": x.dtx_rows,
                            "families": ", ".join(x.families[:4]),
                            "tracked": ", ".join(x.tracked_by[:3]) or "—",
                            "missing": ", ".join(x.missing_from[:3]) or "—",
                        } for x in q.coverage], columns=[
                            {"name": "code", "label": "Code", "field": "code",
                             "align": "left", "sortable": True},
                            {"name": "status", "label": "Status", "field": "status",
                             "align": "left", "sortable": True},
                            {"name": "rows", "label": "DTx rows", "field": "rows",
                             "align": "center", "sortable": True},
                            {"name": "families", "label": "Used by", "field": "families",
                             "align": "left"},
                            {"name": "tracked", "label": "Tracked by", "field": "tracked",
                             "align": "left"},
                            {"name": "missing", "label": "Missing from", "field": "missing",
                             "align": "left"},
                        ], pagination=15).classes("w-full").props("dense flat")

        def _metric_row(metrics) -> None:
            with ui.row().classes("gap-2 flex-wrap mt-1"):
                for label, value, kind in metrics:
                    colour = theme.STATUS.get(kind, theme.STATUS["info"])
                    with ui.element("div").classes("rounded px-2 py-1 min-w-[7rem]") \
                            .style(f"background:{theme.SURFACE_2};"
                                   f"border:1px solid {colour}55"):
                        ui.label(str(value)).classes("text-base font-bold") \
                            .style(f"color:{colour}")
                        ui.label(label).classes("text-[10px] sx-muted")

        # ---------------------------------------------------------------- map
        def _identity_of() -> dict:
            """filename -> the identity the mapping is stored under."""
            return {f: store.harness_identity(
                        state["harnesses"][f].def_id,
                        state["metas"][f].harness or state["harnesses"][f].name)
                    for f in state["harnesses"]}

        def _persist() -> None:
            """Keep the mapping and the cleanup ticks for next time."""
            try:
                store.save({
                    "mapping": store.remember_mapping(state["mapping"],
                                                      _identity_of()),
                    "cleanup": store.remember_cleanup(state["cleanup"]),
                    "fixes": dict(state["fixes"]),
                    "dismissed": sorted(state["dismissed"]),
                })
            except Exception as exc:  # noqa: BLE001 — never block the workbench
                ui.notify(f"Could not save the workbench: {exc}", type="warning")

        def _labels() -> dict:
            return {f: (state["metas"][f].harness or state["harnesses"][f].name)
                    for f in state["harnesses"]}

        @ui.refreshable
        def mapping_view() -> None:
            if not state["families"]:
                return
            from splice.dtxcircuits import matching

            meta = state["dtx_meta"]
            mapped = state["mapping"]
            labels = _labels()
            suggestions = matching.suggest(
                [f for f, _n in state["families"]], labels)
            orphans = matching.orphans(labels, suggestions)
            connected = sum(1 for v in mapped.values() if v)

            with c.card("3 · Map families to complexity files",
                        f"DTx {meta.program or '?'} · phase {meta.phase or '?'} "
                        f"· {len(state['families'])} families · "
                        f"{len(state['harnesses'])} file(s). A family may take "
                        f"several harnesses."):
                with ui.row().classes("gap-2 flex-wrap items-center"):
                    c.chip("ok", f"{connected} connected")
                    if len(state["families"]) - connected:
                        c.chip("blocker",
                               f"{len(state['families']) - connected} open")
                    if orphans:
                        c.chip("review", f"{len(orphans)} with no likely family")
                    for f in (state["corr"].blocking if state["corr"] else []):
                        c.chip("blocker", f"{f.filename}: {f.detail}")
                    ui.checkbox("Only unconnected", value=state["only_open"],
                                on_change=lambda e: (
                                    state.update(only_open=e.value),
                                    mapping_view.refresh())) \
                        .props("dense").classes("text-xs")

                rows = [(f, n) for f, n in state["families"]
                        if not (state["only_open"] and mapped.get(f))]
                if not rows:
                    c.chip("ok", "Every family is connected")

                with ui.element("div").classes("w-full grid gap-x-2 gap-y-1") \
                        .style(GRID):
                    for title in ("DTx harness family", "",
                                  "Harness complexity file(s)",
                                  "Suggested — click to add"):
                        ui.label(title).classes(
                            "text-[10px] font-bold tracking-wide sx-muted")
                    for family, n_rows in rows:
                        chosen = mapped.get(family, [])
                        _family_cell(family, n_rows, len(chosen))
                        ui.html(_line(bool(chosen)))
                        _select_cell(family, chosen, suggestions, orphans, labels)
                        _candidates_cell(family, suggestions.get(family, []),
                                         chosen)

                with ui.row().classes("items-center gap-3 mt-2"):
                    ui.button("Run analysis", icon="play_arrow",
                              on_click=lambda: run()).props("unelevated dense") \
                        .set_enabled(any(mapped.values()))
                    ui.label("Only connected families are analyzed; each "
                             "family × harness pairing is resolved separately.") \
                        .classes("text-[10px] sx-muted")
                    if _open_issues():
                        c.chip("blocker",
                               f"{len(_open_issues())} sales-code expression(s) "
                               "still malformed — their circuits will read as "
                               "never built")

        def _family_cell(family: str, n_rows: int, n_mapped: int) -> None:
            with ui.element("div").classes(
                    "rounded px-2 flex items-center justify-between gap-1") \
                    .style(f"min-height:{ROW_H}px;background:{theme.SURFACE_2};"
                           f"border:1px solid {theme.LINE}"):
                ui.label(family).classes("text-[11px] font-semibold truncate")
                text = str(n_rows) if n_mapped < 2 else f"{n_rows} · ×{n_mapped}"
                ui.label(text).classes("text-[10px] sx-muted shrink-0")

        def _select_cell(family: str, chosen: list, suggestions, orphans: set,
                         labels: dict) -> None:
            """Multi-select of complexity files, with the picks shown as
            removable chips beneath it."""
            with ui.element("div").classes("flex flex-col justify-center gap-1") \
                    .style(f"min-height:{ROW_H}px"):
                from splice.dtxcircuits import matching
                select = ui.select(
                    dict(matching.rank_options(family, labels, suggestions,
                                               orphans)),
                    value=list(chosen), multiple=True,
                    label=None if chosen else "add harness…",
                ).props("dense outlined use-chips=false options-dense") \
                    .classes("w-full text-[11px]")
                select.on_value_change(
                    lambda e, fam=family: _set_mapping(fam, e.value))
                if chosen:
                    with ui.row().classes("gap-1 flex-wrap"):
                        for filename in chosen:
                            _mapped_chip(family, filename, labels)

        def _mapped_chip(family: str, filename: str, labels: dict) -> None:
            harness = state["harnesses"].get(filename)
            detail = (f"def {harness.def_id} · {len(harness.builds)}b · "
                      f"{len(harness.complexity_codes)}c" if harness else "")
            with ui.row().classes(
                    "items-center gap-1 rounded px-2 py-0.5 shrink-0") \
                    .style(f"background:{GREEN}1f;border:1px solid {GREEN}66"):
                ui.label(labels.get(filename, filename)) \
                    .classes("text-[10px] font-semibold").style(f"color:{GREEN}")
                if detail:
                    ui.label(detail).classes("text-[10px] sx-muted")
                ui.button(icon="close",
                          on_click=lambda f=family, n=filename: _remove(f, n)) \
                    .props("flat dense round size=xs")

        def _candidates_cell(family: str, suggestions, chosen: list) -> None:
            with ui.element("div").classes("flex items-center gap-1 flex-wrap") \
                    .style(f"min-height:{ROW_H}px"):
                available = [s for s in suggestions if s.key not in chosen]
                if not available:
                    ui.label("—" if chosen else "no candidate") \
                        .classes("text-[10px] sx-muted")
                    return
                for s in available:
                    _chip(s.key, s.label, s.score, family=family,
                          tooltip=s.reason)

        def _chip(filename: str, label: str, sscore, *, family: str,
                  tooltip: str = "") -> None:
            """A suggestion. Clicking adds it to that family's mapping."""
            strong = sscore is not None and sscore >= 0.7
            colour = GREEN if strong else theme.STATUS["review"]
            chip = ui.element("div").classes(
                "rounded px-2 py-0.5 cursor-pointer shrink-0 truncate") \
                .style(f"background:{colour}1f;border:1px solid {colour}66;"
                       f"max-width:12rem")
            with chip:
                text = label if sscore is None else f"{label}  {sscore:.0%}"
                ui.label(text).classes("text-[10px] font-semibold truncate") \
                    .style(f"color:{colour}")
                if tooltip:
                    ui.tooltip(tooltip)
            chip.on("click", lambda _e, f=filename, fam=family: _add(fam, f))

        def _set_mapping(family: str, values) -> None:
            # de-duplicate while preserving the order the SE picked
            state["mapping"][family] = list(dict.fromkeys(values or []))
            _invalidate()

        def _add(family: str, filename: str) -> None:
            from splice.dtxcircuits import matching
            matching.add_mapping(state["mapping"], family, filename)
            _invalidate()

        def _remove(family: str, filename: str) -> None:
            from splice.dtxcircuits import matching
            matching.remove_mapping(state["mapping"], family, filename)
            _invalidate()

        def _invalidate() -> None:
            """A mapping change makes any existing analysis stale."""
            state["entries"] = state["charts"] = []
            _persist()
            _measure()
            chart_view.refresh()
            mapping_view.refresh()
            results_view.refresh()

        mapping_view()

        # ------------------------------------------------------------ results
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

            with c.card("4 · Review"):
                _cleanup_bar()
                with ui.row().classes("w-full gap-4 items-start no-wrap"):
                    with ui.column().classes("gap-1 min-w-[15rem]"):
                        ui.label("FAMILY × HARNESS").classes(
                            "text-[10px] font-bold tracking-widest sx-muted")
                        for e in entries:
                            _master_row(e)
                    with ui.column().classes("flex-1 min-w-0 gap-2"):
                        _detail(entry)

        def _master_row(entry) -> None:
            a = entry.analysis
            n_find = len(a.findings) + len(a.cnum_findings)
            active = entry.label == state["selected"]
            row = ui.element("div").classes(
                "rounded px-2 py-1.5 cursor-pointer w-full") \
                .style(f"background:{theme.BRAND}26" if active
                       else f"background:{theme.SURFACE_2}")
            with row:
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.icon("report" if n_find else "check_circle") \
                        .classes("text-sm") \
                        .style(f"color:{RED if n_find else GREEN}")
                    with ui.column().classes("gap-0 min-w-0"):
                        ui.label(entry.family).classes(
                            "text-xs font-semibold truncate")
                        ui.label(f"{a.harness} · {len(a.circuits)} ckt"
                                 + (f" · {n_find} finding(s)" if n_find else "")) \
                            .classes("text-[10px] sx-muted truncate")
            row.on("click", lambda _e, lbl=entry.label: (
                state.update(selected=lbl), results_view.refresh()))

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
                                                _persist(),
                                                results_view.refresh())) \
                        .props("flat dense size=sm")
                ui.space()
                ui.button("Export review (.xlsx)", icon="download",
                          on_click=lambda: _export()).props("outline dense")

        async def _export() -> None:
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
                ui.download(data, "Circuit_Applicability_Review.xlsx")

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
            _persist()
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
                ui.label("FILTER").classes(
                    "text-[10px] font-bold tracking-widest sx-muted")
                _filter_chip("Findings", f["findings"],
                             lambda: _toggle_flag("findings"),
                             len([x for x in a.circuits if x.is_finding]))
                _filter_chip("Needs review", f["needs_review"],
                             lambda: _toggle_flag("needs_review"),
                             len([x for x in a.circuits
                                  if x.is_finding or x.relies_on_untracked]))
                for verdict, n in a.counts.items():
                    if n:
                        _filter_chip(verdict, verdict in f["verdicts"],
                                     lambda v=verdict: _toggle_verdict(v), n)
                ui.select({None: "any condition",
                           **{x: x for x in conditions}},
                          value=f["condition"], label=None,
                          on_change=lambda e: _set_condition(e.value)) \
                    .props("dense outlined options-dense").classes(
                        "text-[11px] min-w-[12rem]")
                if f["findings"] or f["needs_review"] or f["verdicts"] \
                        or f["condition"]:
                    ui.button("Clear", icon="filter_alt_off",
                              on_click=_clear_filters).props("flat dense size=sm")

        def _filter_chip(label: str, active: bool, on_click, count: int) -> None:
            colour = theme.BRAND if active else theme.LINE
            chip = ui.element("div").classes(
                "rounded-full px-2 py-0.5 cursor-pointer shrink-0") \
                .style(f"background:{theme.BRAND}26;border:1px solid {colour}"
                       if active else
                       f"background:{theme.SURFACE_2};border:1px solid {colour}")
            with chip:
                ui.label(f"{label} · {count}").classes("text-[10px] font-semibold") \
                    .style(f"color:{theme.BRAND}" if active else "")
            chip.on("click", lambda _e: on_click())

        def _circuit_table(entry) -> None:
            a = entry.analysis
            shown = [x for x in a.circuits if _passes(a, x, "circuit")]
            ui.label(f"{len(shown)} of {len(a.circuits)} circuit(s) shown · tick "
                     f"a row to add it to {report_mod.CLEANUP_COLUMN}") \
                .classes("text-[10px] sx-muted")
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
                .classes("text-[10px] sx-muted")
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
                    .style(f"background:{theme.BRAND}1a" if selected
                           else f"background:{theme.SURFACE_2}"):
                ui.checkbox(value=selected,
                            on_change=lambda _e, k=kind, i=ident:
                                _toggle_cleanup(entry, k, i)) \
                    .props("dense size=xs")
                ui.label(ident).classes("text-[11px] font-semibold w-24 shrink-0")
                c.chip(VERDICT_KIND.get(verdict, "info"), verdict)
                ui.label(condition).classes("text-[10px] sx-mono w-40 truncate")
                ui.label(builds).classes("text-[10px] sx-muted w-14 shrink-0")
                ui.label(carried).classes("text-[10px] sx-muted truncate flex-1")
                if untracked:
                    c.chip("review", f"untracked: {untracked}")

        def _gap_view(entry) -> None:
            a = entry.analysis
            ui.label("Sales codes the DTx conditions on for this family that its "
                     "complexity file does not track. They are read as PRESENT, "
                     "so every circuit below applies more widely than the data "
                     "can justify.").classes("text-[10px] sx-muted")
            if not a.code_gaps:
                c.chip("ok", "Every code the DTx uses here is tracked")
            for g in a.code_gaps:
                selected = _is_selected(entry, "gap", g.code)
                with ui.row().classes(
                        "items-center gap-2 w-full no-wrap rounded px-2 py-1") \
                        .style(f"background:{theme.BRAND}1a" if selected
                               else f"background:{theme.SURFACE_2}"):
                    ui.checkbox(value=selected,
                                on_change=lambda _e, code=g.code:
                                    _toggle_cleanup(entry, "gap", code)) \
                        .props("dense size=xs")
                    ui.label(g.code).classes("text-[11px] font-semibold w-20")
                    ui.label(f"{g.occurrences} DTx row(s)") \
                        .classes("text-[10px] sx-muted w-28")
                    ui.label("circuits: " + ", ".join(g.circuits[:8])) \
                        .classes("text-[10px] sx-muted truncate flex-1")
            if a.unused_codes:
                ui.label("Tracked by the complexity file but never conditioned "
                         "on by a DTx circuit in this family:").classes(
                    "text-[10px] sx-muted mt-2")
                ui.label(", ".join(a.unused_codes)).classes("text-[10px] sx-mono")

        results_view()

        # measured only once an analysis exists, so it is placed after it
        quality_view()

        # ---------------------------------------------------------- 6 · chart
        @ui.refreshable
        def chart_view() -> None:
            charts = state["charts"]
            if not charts:
                return
            with c.card("6 · Circuit chart",
                        "Which part number carries which wire, per harness "
                        "family. The DTx condition flows through the whole "
                        "circuit and is restated in each harness's own codes; "
                        "a circuit reaching three or more cavities gets a "
                        "splice. Same layout as the Circuit Summary that "
                        "Circuit Health reads, so this feeds straight back."):
                with ui.row().classes("gap-2 flex-wrap items-center"):
                    c.chip("info", f"{len(charts)} chart(s) · "
                                   f"{sum(len(x.rows) for x in charts)} circuit end(s)")
                    spliced = sum(len(x.splices) for x in charts)
                    if spliced:
                        c.chip("review", f"{spliced} circuit(s) need a splice")
                    findings = sum(x.findings for x in charts)
                    c.chip("blocker" if findings else "ok",
                           f"{findings} row(s) no build carries"
                           if findings else "Every row is carried by a build")
                    ui.button("Download chart (.xlsx)", icon="download",
                              on_click=lambda: _download_chart()) \
                        .props("outline dense no-caps")

                for chart in charts:
                    with ui.expansion(
                            f"{chart.family} → {chart.harness}"
                            f"   ·  {chart.circuits} circuit(s)"
                            f"  ·  {len(chart.part_numbers)} part number(s)"
                            + (f"  ·  {len(chart.splices)} splice(s)"
                               if chart.splices else "")
                            + (f"  ·  {chart.findings} never built"
                               if chart.findings else ""),
                            value=state["chart_open"] == chart.block_title) \
                            .classes("w-full").props("dense") \
                            .on_value_change(
                                lambda e, t=chart.block_title:
                                    state.update(chart_open=t if e.value else None)):
                        _chart_table(chart)

        def _chart_table(chart) -> None:
            if not chart.rows:
                c.empty("No circuit ends for this family.", icon="table_rows")
                return
            columns = [
                {"name": "circuit", "label": "Circuit", "field": "circuit",
                 "align": "left", "sortable": True},
                {"name": "cnum", "label": "CNUM", "field": "cnum",
                 "align": "left", "sortable": True},
                {"name": "cavity", "label": "Cav", "field": "cavity",
                 "align": "center"},
                {"name": "expression", "label": "Sales code (DTx)",
                 "field": "expression", "align": "left"},
                {"name": "harness_expression", "label": "…in this harness",
                 "field": "harness_expression", "align": "left"},
            ] + [
                # the part number's tail is what an SE reads; the full number
                # stays in the tooltip and in the workbook
                {"name": pn, "label": pn[-6:], "field": pn, "align": "center",
                 "headerStyle": f"writing-mode:vertical-rl;color:{theme.BRAND}"}
                for pn in chart.part_numbers
            ]
            rows = []
            for row in chart.rows:
                record = {"circuit": row.circuit,
                          "cnum": ("⚡ " if row.is_splice else "") + row.cnum,
                          "cavity": row.cavity,
                          "expression": row.expression or "—",
                          "harness_expression": (
                              row.harness_expression
                              or ("—" if row.expression else "")),
                          "_never": row.is_finding}
                record.update(dict(zip(chart.part_numbers,
                                       row.marks(chart.part_numbers))))
                rows.append(record)
            table = ui.table(rows=rows, columns=columns, pagination=25) \
                .classes("w-full").props("dense flat")
            # an empty row is the finding, so it must not read as an empty row
            table.add_slot("body", r"""
                <q-tr :props="props" :class="props.row._never ? 'sx-never' : ''">
                  <q-td v-for="col in props.cols" :key="col.name" :props="props">
                    {{ col.value }}
                  </q-td>
                </q-tr>
            """)
            ui.label(f"Coverage: " + "  ".join(
                f"{pn[-6:]} {chart.coverage(pn)}/{len(chart.rows)}"
                for pn in chart.part_numbers)).classes("text-[10px] sx-mono sx-muted")

        async def _download_chart() -> None:
            meta = state["dtx_meta"]
            data = await c.run_engine(
                chart_mod.build_chart_workbook, list(state["charts"]),
                meta.program if meta else "", meta.phase if meta else "",
                running="Building the circuit chart…", done="Chart ready")
            if data is not None:
                ui.download(data, "Circuit_Chart.xlsx")

        chart_view()

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

                report(0.80, "Checking the Sales Code column…")
                issues = integrity.scan(rows)

                report(0.85, "Checking programme and phase…")
                corr = correspond.check(meta, list(metas.values()))

                report(0.92, "Auto-matching families…")
                families = sorted({r.harness_family for r in rows})
                counts = {f: sum(1 for r in rows if r.harness_family == f)
                          for f in families}
                from splice.dtxcircuits import matching
                exact = matching.auto_map(
                    families,
                    {f: (metas[f].harness or harnesses[f].name) for f in harnesses})
                # a family holds a LIST of harnesses; auto-connect seeds one
                mapping = {family: [filename] for family, filename in exact.items()}
                # a mapping the SE built in an earlier session wins over the
                # automatic one — it was a decision, this is only a guess
                identity_of = {f: store.harness_identity(
                                   harnesses[f].def_id,
                                   metas[f].harness or harnesses[f].name)
                               for f in harnesses}
                restored = store.restore_mapping(
                    state["stored"].get("mapping", {}), identity_of)
                mapping.update(restored)
                report(1.0, "Done")
                return (rows, meta, [(f, counts[f]) for f in families],
                        harnesses, metas, mapping, corr, failed, len(restored),
                        issues)

            out = await c.run_engine_progress(
                work, progress, running="Reading files…", done="Files loaded")
            if out is None:
                return
            (rows, meta, families, harnesses, metas, mapping, corr, failed,
             restored_count, issues) = out
            state.update(rows=rows, dtx_meta=meta, families=families,
                         harnesses=harnesses, metas=metas, mapping=mapping,
                         corr=corr, entries=[], charts=[], selected=None,
                         issues=issues)
            if restored_count:
                ui.notify(f"Restored {restored_count} mapping(s) from your last "
                          "session", type="info")
            # a repair confirmed on an earlier DTx applies to any later one
            # repeating the same text — say so, or it happens invisibly
            carried = sum(1 for i in issues if i.expression in state["fixes"])
            if carried:
                ui.notify(f"{carried} sales-code repair(s) carried over from an "
                          "earlier session and were applied to this DTx",
                          type="info", multi_line=True)
            for problem in failed[:5]:
                ui.notify(problem, type="negative", multi_line=True,
                          close_button=True)
            ui.notify(f"{len(mapping)} of {len(families)} families matched "
                      "automatically", type="positive")
            _measure()
            integrity_view.refresh()
            mapping_view.refresh()
            results_view.refresh()

        def _measure() -> None:
            """Re-measure the DTx, but only once there is an analysis to
            measure against. Before that the never-built and coverage numbers
            would all read zero — a clean bill of health the run has not
            earned, and the worst thing to put in front of a customer."""
            if not state["rows"] or state["dtx_meta"] is None \
                    or not state["entries"]:
                state["quality"] = None
            else:
                state["quality"] = quality_mod.assess(
                    state["rows"], state["dtx_meta"], state["issues"],
                    state["entries"], state["fixes"])
            quality_view.refresh()

        def _conditions_by(rows, attribute: str) -> dict:
            """Condition per circuit (or per CNUM) exactly as the DTx stated it."""
            from splice.dtxcircuits.analyze import union_condition
            grouped: dict = {}
            for row in rows:
                key = getattr(row, attribute, "")
                if key:
                    grouped.setdefault(key, []).append(row)
            return {key: (union_condition(group) or "")
                    for key, group in grouped.items()}

        async def run() -> None:
            if not any(state["mapping"].values()):
                ui.notify("Connect at least one family first", type="warning")
                return

            def work(report):
                # repairs first: an unfixed expression is false everywhere and
                # would make its circuits read as never built
                raw_rows = state["rows"]
                rows = integrity.apply_fixes(raw_rows, state["fixes"])
                pairs = [(family, filename)
                         for family, files in sorted(state["mapping"].items())
                         for filename in files]
                out = []
                for index, (family, filename) in enumerate(pairs, start=1):
                    harness = state["harnesses"][filename]
                    label = (state["metas"][filename].harness or harness.name)
                    report(index / max(len(pairs), 1),
                           f"Resolving {family} → {label} "
                           f"({index} of {len(pairs)})…")
                    family_rows = [r for r in rows if r.harness_family == family]
                    analysis = analyze_harness(family_rows, harness,
                                               harness_name=label)
                    # the same unions over the UNREPAIRED rows, so the export can
                    # show what the DTx said next to what was analysed
                    original = [r for r in raw_rows if r.harness_family == family]
                    out.append(report_mod.Entry(
                        label=f"{family} → {label}", family=family,
                        filename=filename, analysis=analysis,
                        original_circuit_conditions=_conditions_by(original, "circuit"),
                        original_cnum_conditions=_conditions_by(original, "cnum"),
                        complexity=harness))
                return out

            out = await c.run_engine_progress(
                work, progress, running="Analyzing…", done="Analysis ready")
            if out is not None:
                state["entries"] = out
                state["selected"] = None
                # Never-built circuits and connectors, and every sales-code
                # gap, go into the review by default — they are exactly what
                # the customer has to fix in the next export. Anything the SE
                # has explicitly unticked stays out.
                state["charts"] = chart_mod.build_charts(
                    out, integrity.apply_fixes(state["rows"], state["fixes"]))
                picked = report_mod.auto_select(out, state["dismissed"])
                added = [k for k in picked if k not in state["cleanup"]]
                state["cleanup"].update({k: v for k, v in picked.items()
                                         if k in added})
                if added:
                    ui.notify(f"{len(added)} finding(s) added to the review "
                              "automatically — untick any you do not want the "
                              "customer to see", type="info", multi_line=True)
                _persist()
                _measure()
                chart_view.refresh()
                # Selections are NOT pruned to this run. A tick made against a
                # family that is not mapped today is still a real cleanup task,
                # and dropping it here would quietly delete it from the store.
                results_view.refresh()
