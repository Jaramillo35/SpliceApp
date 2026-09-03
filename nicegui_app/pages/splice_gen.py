"""Splice Generation — NiceGUI page over splice.splice_gen.

Archetype A (converter): inputs panel with one gated primary, result panel
that exists before the run. The four tables and the output workbook land in
the result panel; the sales-code editor is its own card below the grid,
empty until there is a result, and rebuilt whenever one arrives (a run, or
an "Apply to row" that refreshes the analysis in place).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from nicegui import ui

from nicegui_app import components as c

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "downloads"
SAMPLE = ASSETS / "Z913_example_input.xlsx"
OUTPUT_STEM = "Wiring_Harness_Output"
TABLES = (("Configurations", "configurations_df"),
          ("Generated connections", "generated_connections_df"),
          ("Harness print matrix", "harness_print_matrix_df"),
          ("OptionPerCkt (as read)", "option_df"))


@ui.page("/splice-generation")
def page() -> None:
    state: dict = {"file": None, "result": None}

    with c.frame("Splice Generation",
                 "One Complexity + OptionPerCkt workbook → configurations, "
                 "generated connections, print matrix, and the output Excel."):
        inputs, result = c.converter(
            "Drop one workbook with the Complexity and OptionPerCkt sheets. "
            "The analysis lists every configuration, the generated "
            "connections and the harness print matrix, and builds the output "
            "workbook. The sales-code editor below opens once there is a "
            "result.",
            inputs_caption="One .xlsx with both sheets. CAN mode adds the CAN "
                           "validation pass.")

        with inputs:
            c.upload_row("Splice input workbook (.xlsx)",
                         lambda n, b: state.update(file=(n, b)),
                         accept=".xlsx,.xlsm")
            can_mode = ui.switch("CAN mode")
            if SAMPLE.exists():
                c.download(SAMPLE.name, lambda: SAMPLE.read_bytes())
            c.action("Run analysis", lambda: analyze(),
                     needs=lambda: ["Splice input workbook"] if not state["file"] else [])

        # the editor lives under the grid at full width; it is empty until
        # a result exists and is rebuilt whenever one arrives
        editor = ui.column().classes("w-full gap-0")

        def show_result(r: dict) -> None:
            with result.show():
                first = True
                for name, key in TABLES:
                    df = r.get(key)
                    if df is None or getattr(df, "empty", True):
                        continue
                    with ui.expansion(f"{name} ({len(df)})", value=first) \
                            .classes("w-full").props("dense"):
                        c.frame_table(df, cap=300,
                                      labels={str(col): str(col) for col in df.columns})
                    first = False
            with result.actions:
                c.download(c.export_name(OUTPUT_STEM),
                           lambda: r["output_excel_bytes"])
            render_editor(r)

        def render_editor(r: dict) -> None:
            editor.clear()
            option_df = r["option_df"]
            circuits = sorted(option_df["Circuit"].dropna().astype(str)
                              .str.strip().unique().tolist())
            if not circuits:
                return
            from splice.splice_gen import (
                evaluate_expression_against_all_pns,
                generate_expression_for_selected_pns,
                generate_sales_code_expression,
                get_candidate_codes_from_option_df,
                simplify_expression_for_display,
                validate_generated_expression,
            )
            harness_cols = sorted({k.split("__")[0] for k in r["harness_code_map"]})
            generated: dict = {"expr": None}

            with editor, c.card("Sales-code editor",
                                "Pick a circuit row, toggle which PNs should apply, "
                                "generate a validated expression, apply it — the "
                                "analysis refreshes in place."):
                with ui.row().classes("w-full gap-3 items-start no-wrap"):
                    circuit_sel = ui.select(circuits, value=circuits[0],
                                            label="Circuit").classes("w-56 shrink-0")
                    row_sel = ui.select([], label="Row").classes("grow min-w-0")
                code_in = ui.input("Sales Code").classes("w-full sx-mono").props("dense")
                ui.label("Part numbers this expression applies to").classes("sx-caption")
                grid = ui.row().classes("gap-2 flex-wrap")
                verdict = ui.column().classes("gap-1")
                boxes: dict[str, ui.checkbox] = {}

                def rows_for(circuit: str):
                    mask = option_df["Circuit"].astype(str).str.strip() == circuit
                    return option_df[mask]

                def refresh_rows() -> None:
                    subset = rows_for(circuit_sel.value)
                    options = {int(i): f"{i}: {row['CNUM']} | Pin {row['Pin']} | "
                                       f"{row['Sales Code']}"
                               for i, row in subset.iterrows()}
                    row_sel.set_options(options, value=next(iter(options), None))
                    refresh_row()

                def refresh_row() -> None:
                    if row_sel.value is None:
                        return
                    code_in.value = str(option_df.loc[row_sel.value, "Sales Code"])
                    refresh_grid()

                def refresh_grid() -> None:
                    grid.clear()
                    verdict.clear()
                    boxes.clear()
                    matched: list[str] = []
                    expr = (code_in.value or "").strip()
                    if expr:
                        try:
                            matched = evaluate_expression_against_all_pns(
                                expr, r["harness_code_map"])
                        except Exception:  # noqa: BLE001 — any parse or eval failure means "not valid"
                            with verdict:
                                c.chip("blocker", "Combination not valid with "
                                                  "available salescodes")
                    with grid:
                        for pn in harness_cols:
                            boxes[pn] = ui.checkbox(pn, value=pn in matched) \
                                .props("dense").classes("sx-mono")

                def generate() -> None:
                    verdict.clear()
                    selected = [pn for pn, box in boxes.items() if box.value]
                    candidates = get_candidate_codes_from_option_df(
                        option_df, circuit_name=circuit_sel.value)
                    targets = [hk for hk in r["harness_code_map"]
                               if hk.split("__")[0] in set(selected)]
                    expr = ""
                    if targets and candidates:
                        expr = generate_sales_code_expression(
                            target_harnesses=targets,
                            harness_code_map=r["harness_code_map"],
                            candidate_codes=candidates)
                    else:
                        expr = generate_expression_for_selected_pns(
                            selected, r["harness_code_map"])
                    if not expr or not validate_generated_expression(
                            expr, selected, r["harness_code_map"]):
                        generated["expr"] = None
                        with verdict:
                            c.chip("blocker", "Combination not valid with "
                                              "available salescodes")
                        return
                    generated["expr"] = simplify_expression_for_display(expr)
                    code_in.value = generated["expr"]
                    with verdict:
                        c.chip("ok", f"Generated: {generated['expr']}")

                async def apply() -> None:
                    expr = generated["expr"] or (code_in.value or "").strip()
                    if not expr or row_sel.value is None:
                        ui.notify("Generate or type a sales code first", type="warning")
                        return
                    target_row = row_sel.value

                    def work():
                        from splice.splice_gen import run_analysis_from_option_df
                        updated = option_df.copy()
                        updated.loc[target_row, "Sales Code"] = expr
                        with tempfile.TemporaryDirectory(prefix="ng_splice_") as td:
                            path = Path(td) / state["file"][0]
                            path.write_bytes(state["file"][1])
                            return run_analysis_from_option_df(path, updated)

                    refreshed = await c.run_engine(
                        work, running="Applying and refreshing the analysis…",
                        done="Sales code applied")
                    if refreshed is not None:
                        state["result"] = refreshed
                        show_result(refreshed)

                circuit_sel.on_value_change(lambda: refresh_rows())
                row_sel.on_value_change(lambda: refresh_row())
                code_in.on("blur", lambda: refresh_grid())
                code_in.on("keydown.enter", lambda: refresh_grid())
                with ui.row().classes("gap-2"):
                    ui.button("Generate from selected PNs", icon="auto_fix_high",
                              on_click=generate).props("outline no-caps")
                    ui.button("Apply to row", icon="done",
                              on_click=apply).props("unelevated no-caps")
                refresh_rows()

        async def analyze() -> None:
            def work():
                from splice.splice_gen import run_analysis
                with tempfile.TemporaryDirectory(prefix="ng_splice_") as td:
                    path = Path(td) / state["file"][0]
                    path.write_bytes(state["file"][1])
                    return run_analysis(str(path), can_mode=can_mode.value)

            r = await c.run_engine(work, running="Analyzing the workbook…",
                                   done="Analysis complete")
            if r is not None:
                state["result"] = r
                show_result(r)
