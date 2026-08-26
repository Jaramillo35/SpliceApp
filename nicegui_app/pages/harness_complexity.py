"""Harness Complexity — individual-file workbench (ported from WEAVE).

Cross-reference + NEW master complexity (+ optional OLD master and DTx
exports) → affected families → a per-family review matrix the SE edits →
validated individual ``.xlsm`` files generated from the bundled macro
template, one per variant when the master partitions a worksheet.
"""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme

CLASS_LABEL = {
    "confirmed": "Confirmed",
    "inferred": "Inferred",
    "uncertain": "Uncertain",
    "manual": "Manual",
    "excluded": "Excluded",
}


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
    from splice.harnesscx import adapters, checks, compare, export

    state: dict = {
        "crossref": None, "new_master": None, "old_master": None, "dtx": [],
        "cr": None, "universe": set(), "affected": [], "worksheets": [],
        "matrix": None, "files": [],
    }

    with c.frame("Harness Complexity",
                 "Individual harness-complexity files from the master workbook — "
                 "reviewed, validated, macros preserved."):
        _guide()

        with c.card("Inputs",
                    "The cross-reference and NEW master are required. DTx exports "
                    "define which row-9 tokens count as sales codes; the OLD master "
                    "adds the added/removed-code evidence per family."):
            with ui.row().classes("w-full gap-4 flex-wrap"):
                c.upload_zone("Cross-reference workbook (.xlsx)",
                              lambda n, b: state.update(crossref=b), accept=".xlsx")
                c.upload_zone("NEW Master Complexity (.xlsx/.xlsm)",
                              lambda n, b: state.update(new_master=b),
                              accept=".xlsx,.xlsm")
                c.upload_zone("OLD Master Complexity (optional)",
                              lambda n, b: state.update(old_master=b),
                              accept=".xlsx,.xlsm")
                c.upload_zone("DTx export(s) (.xlsx/.csv)",
                              lambda n, b: state["dtx"].append((n, b)),
                              accept=".xlsx,.xlsm,.csv", multiple=True)
            ui.button("Analyze families", icon="play_arrow",
                      on_click=lambda: analyze()).props("unelevated")

        @ui.refreshable
        def render_families() -> None:
            if state["cr"] is None:
                return
            with c.card("Harness families",
                        "Affected families first (with the evidence); any mapped "
                        "worksheet in the NEW master can be opened."):
                if not state["universe"]:
                    c.chip("high", "No DTx sales-code data — row-9 tokens cannot be "
                                   "identified as sales codes. Load a DTx export.")
                aff = state["affected"]
                if aff:
                    ui.label("Affected by this change").classes("text-sm font-semibold")
                    with ui.row().classes("gap-2 flex-wrap"):
                        for a in aff:
                            kind = "blocker" if not a.resolved else \
                                ("high" if a.by_complexity else "info")
                            label = a.worksheet or a.family
                            if a.reasons:
                                label += "  ·  " + "; ".join(a.reasons)
                            if a.worksheet:
                                ui.button(label,
                                          on_click=lambda w=a.worksheet: open_ws(w)) \
                                    .props("outline dense no-caps") \
                                    .style(f"color:{theme.STATUS[kind]};"
                                           f"border-color:{theme.STATUS[kind]}55")
                            else:
                                c.chip(kind, label)
                with ui.row().classes("items-end gap-3 flex-wrap"):
                    ws_sel = ui.select(state["worksheets"], label="Open a family",
                                       with_input=True).classes("w-72").props("dense")
                    ui.button("Open", icon="folder_open",
                              on_click=lambda: open_ws(ws_sel.value)) \
                        .props("outline dense")
            render_workbench()

        async def open_ws(worksheet: str | None) -> None:
            if not worksheet:
                ui.notify("Pick a harness family first", type="warning")
                return
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
                state["matrix"], state["files"] = matrix, []
                render_families.refresh()

        def render_workbench() -> None:
            m = state["matrix"]
            if m is None:
                return
            meta = " · ".join(x for x in (
                f"{m.year} {m.vehicle}".strip(), m.phase, m.harness_name) if x)
            with c.card(f"Workbench — {m.worksheet}", meta):
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
                _render_generate(m)

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
                             "knowingly.").classes("text-xs sx-muted")
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
                ui.table(rows=[{
                    "code": r["code"],
                    "dtx": "✓" if r["in_dtx"] else "",
                    "cx": "✓" if r["in_complexity"] else "✗",
                    "feature": r["feature"],
                    "origin": r["origin"],
                } for r in cov], columns=[
                    {"name": "code", "label": "Sales code", "field": "code",
                     "align": "left", "sortable": True},
                    {"name": "dtx", "label": "In DTx", "field": "dtx", "align": "center"},
                    {"name": "cx", "label": "In complexity", "field": "cx",
                     "align": "center"},
                    {"name": "feature", "label": "Feature", "field": "feature",
                     "align": "left"},
                    {"name": "origin", "label": "Row-9 cell", "field": "origin",
                     "align": "left"},
                ], pagination=15).classes("w-full").props("dense flat")

        def _render_matrix(m) -> None:
            from splice.harnesscx.models import ProposalClass

            ui.label("Applicability matrix").classes("text-sm font-semibold mt-2")
            ui.label("Edit a part number or an X/G mark directly — every proposed "
                     "value shows how it was derived. Tick the boxes (or the "
                     "header box for all) to remove several rows at once.") \
                .classes("text-xs sx-muted")

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
                    render_families.refresh()

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
                    ui.notify(f"Removed {n} part number(s) — they will not appear "
                              "in the generated file" if n else "Tick rows first",
                              type="positive" if n else "warning")
                    render_families.refresh()

                ui.button("Add PN", icon="add", on_click=add_pn).props("outline dense")
                ui.button("Remove selected", icon="delete_sweep",
                          on_click=exclude_selected).props("outline dense color=negative")

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
                .classes("text-xs sx-muted")
            for ce in m.combined_exprs:
                with ui.row().classes("items-center gap-3 flex-wrap w-full"):
                    def toggle(v, ce=ce):
                        ce.include = bool(v.value)
                        state["files"] = []

                    def set_code(v, ce=ce):
                        ce.manual_code = v.value or ""
                        state["files"] = []

                    ui.checkbox("Include", value=ce.include, on_change=toggle)
                    ui.label(ce.original_expr).classes("text-sm sx-mono")
                    if ce.is_equality:
                        c.chip("ok", "equality — auto-resolved: "
                                     + ", ".join(ce.output_codes))
                    ui.input("Sales code(s) to write as", value=ce.manual_code,
                             on_change=set_code).classes("w-56").props("dense")
                    if ce.feature:
                        ui.label(ce.feature).classes("text-xs sx-muted")

        def _render_generate(m) -> None:
            ui.separator().classes("my-2")
            with ui.row().classes("items-end gap-3 flex-wrap"):
                id_in = ui.input("Harness ID (manual)", value=m.harness_id) \
                    .classes("w-48").props("dense")

                async def generate() -> None:
                    def work():
                        return export.generate_files(m, id_in.value or "")

                    out = await c.run_engine(
                        work, running="Generating the individual file(s)…",
                        done="Generation finished")
                    if out is None:
                        return
                    files, problems = out
                    if problems:
                        ui.notify(" · ".join(problems), type="negative",
                                  multi_line=True, close_button=True)
                        return
                    warns = export.unresolved_warnings(m)
                    if warns:
                        ui.notify("Generated with notes: " + " · ".join(warns),
                                  type="warning", multi_line=True, close_button=True)
                    state["files"] = files
                    for data, fname in files:
                        ui.download(data, fname)
                    render_families.refresh()

                ui.button("Generate .xlsm", icon="play_arrow", on_click=generate) \
                    .props("unelevated")
                if m.partition_sides:
                    ui.label(f"→ {len(m.partition_sides)} files "
                             f"({' / '.join(m.partition_sides)})") \
                        .classes("text-xs sx-muted")
            if state["files"]:
                with ui.row().classes("gap-2 flex-wrap"):
                    for data, fname in state["files"]:
                        c.download_button(fname, lambda d=data: d)

        render_families()

        async def analyze() -> None:
            if not (state["crossref"] and state["new_master"]):
                ui.notify("Load the cross-reference and the NEW master first",
                          type="warning")
                return

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
            state.update(cr=cr, _frames=frames, universe=universe,
                         worksheets=sheets, affected=affected,
                         matrix=None, files=[])
            if not sheets:
                ui.notify("No master worksheet matches the cross-reference — "
                          "check the 'Complexity File' column.", type="warning")
            render_families.refresh()
