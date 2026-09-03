"""Harness Complexity — individual-file workbench (ported from WEAVE).

Cross-reference + NEW master complexity (+ optional OLD master and DTx
exports) → affected families → a per-family review matrix the SE edits →
validated individual ``.xlsm`` files generated from the bundled macro
template, one per variant when the master partitions a worksheet.

Archetype B (workbench): a sticky step bar names the four stages from the
first paint — Inputs, Families, Workbench, Generate — and a KPI strip under
it follows the same state. ``sync()`` derives both from ``state`` after
every refresh; nothing sets a step by hand. Every primary is gated on the
inputs it needs, and the generated files are offered as buttons only.
"""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c

CLASS_LABEL = {
    "confirmed": "Confirmed",
    "inferred": "Inferred",
    "uncertain": "Uncertain",
    "manual": "Manual",
    "excluded": "Excluded",
}

STEPS = ("Inputs", "Families", "Workbench", "Generate")

#: what an affected family's status chip says — icon plus word, never colour
AFFECTED_WORD = {"blocker": "unmapped", "high": "codes changed", "info": "DTx change"}


def undecided(matrix) -> list:
    """Combined expressions still waiting on the SE.

    An equality is pre-approved by the engine; any other combined expression
    the SE has not ticked Include on is still a decision to make. The model
    carries no explicit "leave it out" flag, so a deliberate exclusion reads
    as undecided here — the engine does not block on it either way.
    """
    return [ce for ce in matrix.combined_exprs
            if not ce.is_equality and not ce.include]


def _guide() -> None:
    with ui.expansion("How this workbench works — read me first", icon="school") \
            .classes("w-full").props("dense"):
        ui.markdown(
            "**What it does.** The Master Complexity workbook holds one worksheet per "
            "harness family; each individual harness-complexity file is a hand-made "
            "extract of it — part numbers × sales codes. This workbench builds that "
            "extract for you and shows *why* every value was proposed, so you review "
            "decisions instead of retyping cells.\n\n"
            "**The rules it applies.**\n"
            "- Sales codes are the row-9 tokens that also appear in the DTx `Sales Code` "
            "data — phase / PC / market codes are ignored automatically.\n"
            "- The Current P/N comes from the `Current` column; `C/O` resolves to the most "
            "recent valid P/N (marked *Inferred*); `DELETE` / `Cancel` / `N/A` rows are "
            "excluded and never appear in the file.\n"
            "- A row-9 OR-list (`CM5/CVM`) splits into independent columns; an expression "
            "with AND / negation / grouping cannot be split safely and waits for your "
            "decision below. A pure equality (`XH3=XH4`) is auto-resolved: both codes get "
            "a column with identical content.\n"
            "- A worksheet with LEFT/RIGHT (or DRIVER/PASSENGER, CUP vs CM5/CVM) marker "
            "columns generates **one file per variant** — each with that variant's parts "
            "plus the common ones.\n\n"
            "**Your review.** Work the pre-generation checks (a DTx code missing from the "
            "complexity file is the upstream cause of Circuit Health findings later; a "
            "prefix-pair of part numbers is almost always a truncated cell). Edit part "
            "numbers or X/G marks directly in the matrix, decide the combined "
            "expressions, enter the Harness ID, and generate. The template's macros and "
            "`Harness PN` formulas are preserved."
        ).classes("text-sm")


@ui.page("/harness-complexity")
def page() -> None:
    from splice.common.errors import SpliceError
    from splice.harnesscx import adapters, checks, compare, export

    state: dict = {
        "crossref": None, "new_master": None, "old_master": None, "dtx": [],
        "cr": None, "_frames": [], "universe": set(), "affected": [],
        "worksheets": [], "matrix": None, "files": [],
        #: what the last analysis and the last generation had to say —
        #: notes on the page, not toasts (one toast per action: the runner's)
        "analyze_notes": [], "gen_notes": [],
    }
    views: dict = {}

    # ------------------------------------------------------------ derived
    def refresh(*names: str) -> None:
        """Re-render the named views, then the step bar and the KPI strip,
        which are derived from the same state."""
        for name in names:
            views[name].refresh()
        sync()

    def sync() -> None:
        """Step states and KPIs follow the state; nothing sets them by hand."""
        m = state["matrix"]
        if state["cr"] is None:
            steps = {"Inputs": ("current", ""), "Families": ("waiting", ""),
                     "Workbench": ("waiting", ""), "Generate": ("waiting", "")}
        else:
            fam_note = f"{len(state['worksheets'])} families"
            if m is None:
                steps = {
                    "Inputs": ("done", fam_note),
                    "Families": ("current", f"{len(state['affected'])} affected"),
                    "Workbench": ("waiting", ""),
                    "Generate": ("waiting", ""),
                }
            else:
                n_open = len(undecided(m))
                # the engine does not block on an undecided combined
                # expression (export.validate_before_export), so Generate is
                # current, not blocked, while the workbench still has notes
                steps = {
                    "Inputs": ("done", fam_note),
                    "Families": ("done", fam_note),
                    "Workbench": ("current",
                                  f"{n_open} combined expressions to decide"
                                  if n_open else "ready"),
                    "Generate": (("done", f"{len(state['files'])} files")
                                 if state["files"] else ("current", "")),
                }
        for name, (st, note) in steps.items():
            c.set_step(name, st, note)
        views["kpis"].refresh()

    def missing_inputs() -> list[str]:
        out = []
        if not state["crossref"]:
            out.append("the cross-reference workbook")
        if not state["new_master"]:
            out.append("the NEW master")
        return out

    # --------------------------------------------------------------- page
    with c.frame("Harness Complexity",
                 "Individual harness-complexity files from the master workbook — "
                 "reviewed, validated, macros preserved."):
        c.step_bar(*STEPS)

        @ui.refreshable
        def kpi_view() -> None:
            if state["cr"] is None:
                return
            m = state["matrix"]
            n_aff = len(state["affected"])
            with c.kpi_strip():
                c.kpi(len(state["worksheets"]), "Families analysed")
                c.kpi(n_aff, "Affected families", "high" if n_aff else None)
                if m is not None:
                    parts = sum(1 for r in m.rows if not r.excluded)
                    n_open = len(undecided(m))
                    c.kpi(parts, "Part numbers", hint=m.worksheet)
                    c.kpi(n_open, "Combined to decide", "review" if n_open else "ok")
                    c.kpi(m.excluded_count, "Excluded rows",
                          "review" if m.excluded_count else None)
                if state["files"]:
                    c.kpi(len(state["files"]), "Files generated", "ok")

        views["kpis"] = kpi_view
        kpi_view()

        _guide()

        # ---------------------------------------------------- 1 · Inputs
        with c.section("Inputs",
                       "The cross-reference and NEW master are required. DTx exports "
                       "define which row-9 tokens count as sales codes; the OLD master "
                       "adds the added/removed-code evidence per family.",
                       step="Inputs"):
            with ui.row().classes("w-full gap-4 flex-wrap"):
                c.upload_row("Cross-reference workbook (.xlsx)",
                             lambda n, b: state.update(crossref=b), accept=".xlsx")
                c.upload_row("NEW Master Complexity (.xlsx/.xlsm)",
                             lambda n, b: state.update(new_master=b),
                             accept=".xlsx,.xlsm")
                c.upload_row("OLD Master Complexity (optional)",
                             lambda n, b: state.update(old_master=b),
                             accept=".xlsx,.xlsm")
                c.upload_row("DTx export(s) (.xlsx/.csv)",
                             lambda n, b: state["dtx"].append((n, b)),
                             accept=".xlsx,.xlsm,.csv", multiple=True)
            c.action("Analyze families", lambda: analyze(), needs=missing_inputs)

        # -------------------------------------------------- 2 · Families
        @ui.refreshable
        def families_view() -> None:
            if state["cr"] is None:
                return
            with c.section("Harness families",
                           "Affected families first (with the evidence); any mapped "
                           "worksheet in the NEW master can be opened.",
                           step="Families"):
                for kind, text in state["analyze_notes"]:
                    c.note(kind, text)
                if not state["universe"]:
                    c.note("high", "No DTx sales-code data — row-9 tokens cannot be "
                                   "identified as sales codes. Load a DTx export.")
                aff = state["affected"]
                if aff:
                    ui.label("Affected by this change").classes("text-sm font-semibold")
                    with ui.row().classes("gap-2 flex-wrap"):
                        for a in aff:
                            _affected(a)
                with ui.row().classes("items-end gap-3 flex-wrap"):
                    ws_sel = ui.select(state["worksheets"], label="Open a family",
                                       with_input=True).classes("w-72").props("dense")
                    ws_sel.on_value_change(lambda _e: c.recheck())
                    c.action("Open", lambda: open_ws(ws_sel.value),
                             needs=lambda: [] if ws_sel.value else ["a harness family"],
                             icon="folder_open", secondary=True)

        def _affected(a) -> None:
            """One affected family: a button when its worksheet is known,
            a chip when the DTx family could not be mapped. The status is
            the chip's icon and word; the colour only repeats it."""
            kind = "blocker" if not a.resolved else \
                ("high" if a.by_complexity else "info")
            reasons = "; ".join(a.reasons)
            if not a.worksheet:
                c.chip(kind, a.family + (f"  ·  {reasons}" if reasons else ""))
                return
            with ui.button(a.worksheet, on_click=lambda w=a.worksheet: open_ws(w)) \
                    .props("outline dense no-caps"):
                with ui.row().classes("items-center gap-2 no-wrap pl-2"):
                    c.chip(kind, AFFECTED_WORD[kind])
                    if reasons:
                        ui.label(reasons).classes("sx-caption normal-case")

        # ------------------------------------------------- 3 · Workbench
        @ui.refreshable
        def workbench_view() -> None:
            m = state["matrix"]
            if m is None:
                return
            meta = " · ".join(x for x in (
                f"{m.year} {m.vehicle}".strip(), m.phase, m.harness_name) if x)
            with c.section(f"Workbench — {m.worksheet}", meta, step="Workbench"):
                with ui.row().classes("gap-2 flex-wrap"):
                    n_parts = sum(1 for r in m.rows if not r.excluded)
                    c.chip("info", f"{n_parts} part number(s)")
                    if m.excluded_count:
                        c.chip("review", f"{m.excluded_count} excluded "
                                         "(deleted / cancelled / N/A)")
                    c.chip("info", f"{len(m.sales_codes)} sales code(s)")
                    if m.partition_sides:
                        c.chip("high", "partitioned: one file per variant — "
                                       + " / ".join(m.partition_sides))
                    if m.unresolved_count:
                        c.chip("review", f"{m.unresolved_count} row(s) uncertain")

                _render_checks(m)
                _render_matrix(m)
                _render_combined(m)

        def _render_checks(m) -> None:
            cov = checks.coverage_rows(m)
            missing = [r["code"] for r in cov if not r["ok"]]
            lookalikes = checks.pn_lookalikes(m)
            dupes = checks.duplicate_pns(m)
            unmarked = checks.unmarked_parts(m)
            dead = checks.dead_code_columns(m)
            ok = not (missing or lookalikes or dupes or unmarked or dead)

            ui.label("Pre-generation checks").classes("text-sm font-semibold mt-2")
            if ok:
                c.chip("ok", "All checks clean")
            with ui.column().classes("gap-1 w-full"):
                if missing:
                    c.chip("blocker", f"DTx uses {len(missing)} code(s) the complexity "
                                      f"file lacks: {', '.join(missing)}")
                    ui.label("Circuits with these codes cannot be expressed in the "
                             "individual file — the upstream cause of Circuit Health "
                             "option-window findings. Fix the master or accept "
                             "knowingly.").classes("sx-caption")
                for a, b in lookalikes:
                    c.chip("high", f"Truncated-PN lookalikes: {a} vs {b} — "
                                   "one is almost certainly a cut-off cell")
                if dupes:
                    c.chip("high", "Duplicate part number(s): " + ", ".join(dupes))
                if unmarked:
                    c.chip("review", f"{len(unmarked)} part(s) with no X/G under any "
                                     f"code: {', '.join(unmarked[:6])}"
                                     + ("…" if len(unmarked) > 6 else ""))
                if dead:
                    c.chip("review", "Column(s) no part is marked under: "
                                     + ", ".join(dead))

            with ui.expansion(f"Sales-code coverage ({len(cov)} codes)") \
                    .classes("w-full").props("dense"):
                c.frame_table(
                    [{"code": r["code"],
                      "dtx": "yes" if r["in_dtx"] else "no",
                      "cx": "yes" if r["in_complexity"] else "no",
                      "feature": r["feature"],
                      "origin": r["origin"]} for r in cov],
                    labels={"code": "Sales code", "dtx": "In DTx",
                            "cx": "In complexity", "feature": "Feature",
                            "origin": "Row-9 cell"},
                    mono=("code", "origin"), status_field="cx", pagination=15)

        def _render_matrix(m) -> None:
            from splice.harnesscx.models import ProposalClass

            ui.label("Applicability matrix").classes("text-sm font-semibold mt-2")
            ui.label("Edit a part number or an X/G mark directly — every proposed "
                     "value shows how it was derived. Tick the boxes (or the "
                     "header box for all) to exclude several rows at once.") \
                .classes("sx-caption")

            code_cols = [sc.code for sc in m.sales_codes]
            rows = []
            for i, r in enumerate(m.rows):
                if r.excluded:
                    continue
                row = {"_i": i, "Symbol": r.variant_id, "Harness PN": r.current_pn,
                       "Previous": r.previous_pn,
                       "Class": CLASS_LABEL.get(r.current_class.value,
                                                r.current_class.value)}
                if m.partition_sides:
                    row["Partition"] = r.partition_side
                for code in code_cols:
                    row[code] = r.symbols.get(code, "")
                rows.append(row)

            col_defs = [
                {"field": "Symbol", "width": 110, "pinned": "left",
                 "checkboxSelection": True, "headerCheckboxSelection": True},
                {"field": "Harness PN", "editable": True, "width": 150,
                 "pinned": "left", "cellStyle": {"fontWeight": "600"}},
                {"field": "Previous", "width": 130},
                {"field": "Class", "width": 100},
            ]
            if m.partition_sides:
                col_defs.append({"field": "Partition", "editable": True, "width": 110})
            col_defs += [{"field": code, "editable": True, "width": 64,
                          "cellStyle": {"textAlign": "center"}} for code in code_cols]

            # the app's one editable grid: it stays an aggrid
            grid = ui.aggrid({
                "columnDefs": col_defs, "rowData": rows,
                "rowSelection": "multiple",
                "suppressRowClickSelection": True,   # only the checkboxes select
                "defaultColDef": {"resizable": True, "sortable": True,
                                  "suppressMovable": True},
            }).classes("w-full").style("height: 22rem")

            def on_edit(e) -> None:
                data = e.args.get("data", {})
                i = data.get("_i")
                if i is None or not (0 <= i < len(m.rows)):
                    return
                r = m.rows[i]
                pn = str(data.get("Harness PN") or "").strip()
                if pn != r.current_pn:
                    r.current_pn = pn
                    r.current_class = ProposalClass.MANUAL
                    r.current_reason = "edited by the SE"
                if m.partition_sides and "Partition" in data:
                    r.partition_side = str(data.get("Partition") or "").strip().upper()
                for code in code_cols:
                    sym = str(data.get(code) or "").strip().upper()
                    if sym in ("X", "G"):
                        r.symbols[code] = sym
                        r.symbol_class[code] = ProposalClass.MANUAL
                    else:
                        r.symbols.pop(code, None)
                        r.symbol_class.pop(code, None)
                state["files"] = []
                # an edit makes any generated file stale: the Generate step
                # and its download buttons follow, the grid keeps its place
                refresh("generate")

            grid.on("cellValueChanged", on_edit)

            with ui.row().classes("items-end gap-2 flex-wrap"):
                add_in = ui.input("Add part number").classes("w-56").props("dense")

                def add_pn() -> None:
                    pn = (add_in.value or "").strip()
                    if not pn:
                        return
                    from splice.harnesscx.models import MatrixRow
                    m.rows.append(MatrixRow(
                        variant_id="(added)", current_pn=pn, previous_pn="",
                        current_class=ProposalClass.MANUAL,
                        current_reason="added by the SE", current_source="workbench"))
                    add_in.set_value("")
                    state["files"] = []
                    refresh("workbench", "generate")

                async def exclude_selected() -> None:
                    selected = await grid.get_selected_rows()
                    n = 0
                    for row in selected:
                        i = row.get("_i")
                        if i is not None and 0 <= i < len(m.rows):
                            m.rows[i].excluded = True
                            m.rows[i].current_class = ProposalClass.EXCLUDED
                            m.rows[i].current_reason = "excluded by the SE"
                            n += 1
                    state["files"] = []
                    if not n:
                        hint.set_visibility(True)
                        return
                    ui.notify(f"Excluded {n} part number(s) — they will not appear "
                              "in the generated file", type="positive")
                    refresh("workbench", "generate")

                ui.button("Add PN", icon="add", on_click=add_pn).props("outline dense no-caps")
                # excluding only marks rows in memory — not destructive, so
                # not a negative button
                ui.button("Exclude selected rows", icon="playlist_remove",
                          on_click=exclude_selected).props("outline dense no-caps")
            hint = ui.label("Tick rows first").classes("sx-caption")
            hint.set_visibility(False)

        def _render_combined(m) -> None:
            if not m.combined_exprs:
                return
            ui.label("Combined expressions — your call").classes(
                "text-sm font-semibold mt-2")
            ui.label("These row-9 cells mix AND / negation / grouping and cannot be "
                     "split into independent columns without misrepresenting the "
                     "logic. Tick Include to add one; a comma-separated definition "
                     "('CG3, CG4') becomes one column per code with identical "
                     "content. Equalities ('XH3=XH4') are pre-approved.") \
                .classes("sx-caption")
            for ce in m.combined_exprs:
                with ui.row().classes("items-center gap-3 flex-wrap w-full"):
                    def toggle(v, ce=ce):
                        ce.include = bool(v.value)
                        state["files"] = []
                        refresh("generate")

                    def set_code(v, ce=ce):
                        ce.manual_code = v.value or ""
                        state["files"] = []
                        refresh("generate")

                    ui.checkbox("Include", value=ce.include, on_change=toggle)
                    ui.label(ce.original_expr).classes("text-sm sx-mono")
                    if ce.is_equality:
                        c.chip("ok", "equality — auto-resolved: "
                                     + ", ".join(ce.output_codes))
                    ui.input("Sales code(s) to write as", value=ce.manual_code,
                             on_change=set_code).classes("w-56").props("dense")
                    if ce.feature:
                        ui.label(ce.feature).classes("sx-caption")

        # -------------------------------------------------- 4 · Generate
        @ui.refreshable
        def generate_view() -> None:
            m = state["matrix"]
            with c.section("Generate",
                           "The individual file(s) for the open worksheet, from the "
                           "bundled macro template — one per variant when the master "
                           "partitions the worksheet.", step="Generate"):
                if m is None:
                    c.empty("Open a harness family above; its .xlsm file(s) are "
                            "generated here.", icon="table_view")
                    c.action("Generate .xlsm", lambda: None,
                             needs=lambda: ["an open worksheet"])
                    return
                with ui.row().classes("items-end gap-3 flex-wrap"):
                    id_in = ui.input("Harness ID (manual)", value=m.harness_id) \
                        .classes("w-48").props("dense")
                    id_in.on_value_change(lambda _e: c.recheck())

                    def needs() -> list[str]:
                        if state["matrix"] is None:
                            return ["an open worksheet"]
                        return [] if (id_in.value or "").strip() else ["a Harness ID"]

                    c.action("Generate .xlsm", lambda: generate(id_in), needs=needs)
                    if m.partition_sides:
                        ui.label(f"→ {len(m.partition_sides)} files "
                                 f"({' / '.join(m.partition_sides)})") \
                            .classes("sx-caption")
                for kind, text in state["gen_notes"]:
                    c.note(kind, text)
                if state["files"]:
                    items = [(fname, lambda d=data: d) for data, fname in state["files"]]
                    with ui.row().classes("gap-2 flex-wrap items-center"):
                        for name, getter in items:
                            c.download(name, getter)
                        if len(items) > 1:
                            c.downloads(items, label=f"{len(items)} files")

        views.update(families=families_view, workbench=workbench_view,
                     generate=generate_view)
        families_view()
        workbench_view()
        generate_view()
        sync()

        # ------------------------------------------------------- actions
        async def analyze() -> None:
            if not (state["crossref"] and state["new_master"]):
                return   # the action is gated; this is only a guard

            def work():
                cr = adapters.load_crossref(state["crossref"])
                frames = adapters.read_dtx_frames(state["dtx"])
                universe = adapters.dtx_sales_code_universe(frames)
                sheets = [s for s in adapters.master_worksheets(state["new_master"])
                          if s in cr.worksheets]
                changes = []
                if state["old_master"]:
                    changes = compare.compare_complexity(
                        state["old_master"], state["new_master"], cr, universe)
                affected = compare.affected_families({}, changes, cr)
                return cr, frames, universe, sheets, affected

            out = await c.run_engine(work, running="Reading the workbooks…",
                                     done="Families ready")
            if out is None:
                return
            cr, frames, universe, sheets, affected = out
            notes = []
            if not sheets:
                notes.append(("high", "No master worksheet matches the cross-reference "
                                      "— check the 'Complexity File' column."))
            state.update(cr=cr, _frames=frames, universe=universe,
                         worksheets=sheets, affected=affected,
                         matrix=None, files=[], analyze_notes=notes, gen_notes=[])
            refresh("families", "workbench", "generate")

        async def open_ws(worksheet: str | None) -> None:
            if not worksheet:
                return   # the action is gated; this is only a guard
            cr = state["cr"]

            def work():
                fam_codes = adapters.family_dtx_sales_codes(
                    state.get("_frames", []), cr, worksheet)
                return adapters.extract_family_matrix(
                    state["new_master"], worksheet, state["universe"],
                    cr.worksheet_to_canonical.get(worksheet, worksheet),
                    family_dtx_codes=fam_codes)

            matrix = await c.run_engine(
                work, running=f"Building the {worksheet} matrix…",
                done=f"{worksheet} ready")
            if matrix is not None:
                state.update(matrix=matrix, files=[], gen_notes=[])
                refresh("workbench", "generate")

        async def generate(id_in) -> None:
            m = state["matrix"]
            if m is None:
                return   # the action is gated; this is only a guard
            harness_id = id_in.value or ""

            def work():
                files, problems = export.generate_files(m, harness_id)
                if problems:
                    # the runner's toast is the one toast: a blocked export
                    # is its error, not a "finished" followed by a failure
                    raise SpliceError(" · ".join(problems))
                return files

            files = await c.run_engine(
                work, running="Generating the individual file(s)…",
                done="Generation finished")
            if files is None:
                return
            state["files"] = files
            # what the export wants confirmed stays on the page, under the
            # button, where it can be read after the toast is gone
            state["gen_notes"] = [("review", w) for w in export.unresolved_warnings(m)]
            refresh("generate")
