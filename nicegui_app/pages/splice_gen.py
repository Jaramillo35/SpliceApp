"""Splice Generation — NiceGUI page over splice.splice_gen.run_analysis.

Wave 1 scope: upload → analyze → key tables + output workbook download. The
interactive sales-code editor (run_analysis_from_option_df loop) follows in
wave 2 — it is the one genuinely stateful editing flow in the app.
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
                ui.label("Interactive sales-code editing arrives in the next "
                         "wave — use the Streamlit page for that flow meanwhile.") \
                    .classes("text-xs sx-muted")

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
