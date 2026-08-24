"""DTx Compare — NiceGUI page over the enhanced compare + preorder engines."""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c


@ui.page("/dtx-compare")
def page() -> None:
    state: dict = {"old": None, "new": None, "dtcr": None, "result": None}

    with c.frame("DTx Compare",
                 "OLD vs NEW DTx with DTCR tagging → the WEAVE change workbook, "
                 "plus the PreOrder list."):
        with c.card("Inputs", "All three files are required for the compare."):
            with ui.row().classes("w-full gap-4 flex-wrap"):
                c.upload_zone("OLD DTx report (.xls)",
                              lambda n, b: state.update(old=(n, b)), accept=".xls,.xlsx")
                c.upload_zone("NEW DTx report (.xls)",
                              lambda n, b: state.update(new=(n, b)), accept=".xls,.xlsx")
                c.upload_zone("DTCR report (.xls)",
                              lambda n, b: state.update(dtcr=(n, b)), accept=".xls,.xlsx")
            with ui.row().classes("gap-2"):
                ui.button("Generate compare workbook", icon="play_arrow",
                          on_click=lambda: compare()).props("unelevated")
                ui.button("PreOrder list only", icon="playlist_add_check",
                          on_click=lambda: preorder()).props("outline")

        @ui.refreshable
        def render_result() -> None:
            r = state["result"]
            if not r:
                return
            with c.card("Result"):
                with ui.row().classes("gap-6"):
                    for label, key in [("Added CNUMs", "added_cnum_count"),
                                       ("Removed CNUMs", "removed_cnum_count"),
                                       ("Added ckts", "added_circuit_count"),
                                       ("Removed ckts", "removed_circuit_count"),
                                       ("Modified ckts", "modified_circuit_count")]:
                        if key in r:
                            with ui.column().classes("items-center gap-0"):
                                ui.label(str(int(r[key]))).classes("text-xl font-bold")
                                ui.label(label).classes("text-[11px] sx-muted")
                c.download_button(r["output_file_name"], lambda: r["output_excel_bytes"])

        render_result()

        async def compare() -> None:
            if not (state["old"] and state["new"] and state["dtcr"]):
                ui.notify("Load OLD, NEW, and DTCR files first", type="warning")
                return

            def work():
                from splice.dtx_compare.engine import load_dtcr_report
                from splice.dtx_compare.enhanced_report import generate_enhanced_dtx_report
                dtcr = load_dtcr_report(state["dtcr"][1], state["dtcr"][0])
                return generate_enhanced_dtx_report(
                    state["old"][1], state["new"][1],
                    state["old"][0], state["new"][0], dtcr)

            r = await c.run_engine(work, running="Comparing reports and building the workbook…",
                                   done="Compare workbook ready")
            if r is not None:
                state["result"] = r
                render_result.refresh()

        async def preorder() -> None:
            if not (state["old"] and state["new"]):
                ui.notify("Load OLD and NEW files first", type="warning")
                return

            def work():
                import tempfile
                from pathlib import Path
                from splice.dtx_compare import launch_preorder_generation_tool
                with tempfile.TemporaryDirectory(prefix="ng_preorder_") as td:
                    root = Path(td)
                    op, np_ = root / state["old"][0], root / state["new"][0]
                    op.write_bytes(state["old"][1])
                    np_.write_bytes(state["new"][1])
                    return launch_preorder_generation_tool(
                        old_file_path=op, new_file_path=np_)

            r = await c.run_engine(work, running="Generating the PreOrder workbook…",
                                   done="PreOrder ready")
            if r is not None:
                state["result"] = {"output_file_name": r["output_file_name"],
                                   "output_excel_bytes": r["output_excel_bytes"]}
                render_result.refresh()
