"""Splice Generation — NiceGUI page over splice.splice_gen.

Full flow: upload → analyze → tables + output workbook, plus the interactive
sales-code editor (select a circuit row, toggle PN applicability, generate a
validated expression, apply it, and the analysis refreshes in place).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from nicegui import ui

from nicegui_app import components as c

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "downloads"


def _df_table(df, title: str, limit: int = 300) -> None:
    if df is None or getattr(df, "empty", True):
        return
    with ui.expansion(f"{title} ({len(df)})").classes("w-full").props("dense"):
        view = df.head(limit)
        ui.table(rows=view.astype(str).to_dict("records"),
                 columns=[{"name": col, "label": col, "field": col, "align": "left"}
                          for col in view.columns]) \
            .classes("w-full").props("dense flat virtual-scroll") \
            .style("max-height: 22rem")


@ui.page("/splice-generation")
def page() -> None:
    state: dict = {"file": None, "result": None}

    with c.frame("Splice Generation",
                 "One Complexity + OptionPerCkt workbook → configurations, "
                 "generated connections, print matrix, and the output Excel."):
        with c.card("Input", "One workbook with the Complexity and OptionPerCkt sheets."):
            with ui.row().classes("w-full gap-4 flex-wrap items-end"):
                c.upload_zone("Splice input workbook (.xlsx)",
                              lambda n, b: state.update(file=(n, b)),
                              accept=".xlsx,.xlsm")
                with ui.column().classes("gap-2"):
                    can_mode = ui.switch("CAN mode")
                    sample = ASSETS / "Z913_example_input.xlsx"
                    if sample.exists():
                        c.download_button("Z913_example_input.xlsx",
                                          lambda: sample.read_bytes())
            ui.button("Run analysis", icon="play_arrow",
                      on_click=lambda: analyze()).props("unelevated")

        @ui.refreshable
        def render_result() -> None:
            r = state["result"]
            if not r:
                return
            with c.card("Results"):
                _df_table(r.get("configurations_df"), "Configurations")
                _df_table(r.get("generated_connections_df"), "Generated connections")
                _df_table(r.get("harness_print_matrix_df"), "Harness print matrix")
                _df_table(r.get("option_df"), "OptionPerCkt (as read)")
                c.download_button("Wiring_Harness_Output.xlsx",
                                  lambda: r["output_excel_bytes"])
            _editor(r)

        def _editor(r) -> None:
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
            harness_cols = sorted({k.split("__")[0]
                                   for k in r["harness_code_map"]})
            generated: dict = {"expr": None}

            with c.card("Sales-code editor",
                        "Pick a circuit row, toggle which PNs should apply, "
                        "generate a validated expression, apply it — the "
                        "analysis refreshes in place."):
                circuit_sel = ui.select(circuits, value=circuits[0],
                                        label="Circuit").classes("w-56")
                row_sel = ui.select([], label="Row").classes("w-full")
                code_in = ui.input("Sales Code").classes("w-full").props("dense")
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
                    row_sel.set_options(options,
                                        value=next(iter(options), None))
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
                        except Exception:
                            with verdict:
                                c.chip("blocker", "Combination not valid with "
                                                  "available salescodes")
                    with grid:
                        for pn in harness_cols:
                            boxes[pn] = ui.checkbox(pn, value=pn in matched) \
                                .props("dense")

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
                        ui.notify("Generate or type a sales code first",
                                  type="warning")
                        return

                    def work():
                        import tempfile
                        from pathlib import Path
                        from splice.splice_gen import run_analysis_from_option_df
                        updated = option_df.copy()
                        updated.loc[row_sel.value, "Sales Code"] = expr
                        with tempfile.TemporaryDirectory(prefix="ng_splice_") as td:
                            path = Path(td) / state["file"][0]
                            path.write_bytes(state["file"][1])
                            return run_analysis_from_option_df(path, updated)

                    refreshed = await c.run_engine(
                        work, running="Applying and refreshing the analysis…",
                        done="Sales code applied")
                    if refreshed is not None:
                        state["result"] = refreshed
                        render_result.refresh()

                circuit_sel.on_value_change(lambda: refresh_rows())
                row_sel.on_value_change(lambda: refresh_row())
                code_in.on("blur", lambda: refresh_grid())
                with ui.row().classes("gap-2"):
                    ui.button("Generate from selected PNs", icon="auto_fix_high",
                              on_click=generate).props("outline")
                    ui.button("Apply to row", icon="done",
                              on_click=apply).props("unelevated")
                refresh_rows()

        render_result()

        async def analyze() -> None:
            if not state["file"]:
                ui.notify("Load the input workbook first", type="warning")
                return

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
                render_result.refresh()
