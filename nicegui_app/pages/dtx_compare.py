"""DTx Compare — NiceGUI page over the enhanced compare + preorder engines.

Archetype A (converter): inputs panel with one gated primary, result panel
that exists before the run. The PreOrder list is the secondary path and
says so; it no longer shares the primary's colour or its result card.
"""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c

REQUIRED = (("OLD DTx", "old"), ("NEW DTx", "new"), ("DTCR report", "dtcr"))
KPIS = (("Added CNUMs", "added_cnum_count"), ("Removed CNUMs", "removed_cnum_count"),
        ("Added circuits", "added_circuit_count"),
        ("Removed circuits", "removed_circuit_count"),
        ("Modified circuits", "modified_circuit_count"))


@ui.page("/dtx-compare")
def page() -> None:
    state: dict = {"old": None, "new": None, "dtcr": None}

    with c.frame("DTx Compare",
                 "OLD vs NEW DTx with DTCR tagging → the WEAVE change workbook, "
                 "plus the PreOrder list."):
        inputs, result = c.converter(
            "Drop the OLD and NEW DTx exports and the DTCR report. The compare "
            "lists every added, removed and changed circuit and connector, "
            "tagged by DTCR, and builds the change workbook.",
            inputs_caption="All three files are needed for the compare; the "
                           "PreOrder list needs only OLD and NEW.")

        def missing(keys):
            return [label for label, key in REQUIRED if key in keys and not state[key]]

        with inputs:
            c.upload_row("OLD DTx report (.xls)",
                         lambda n, b: state.update(old=(n, b)), accept=".xls,.xlsx")
            c.upload_row("NEW DTx report (.xls)",
                         lambda n, b: state.update(new=(n, b)), accept=".xls,.xlsx")
            c.upload_row("DTCR report (.xls)",
                         lambda n, b: state.update(dtcr=(n, b)), accept=".xls,.xlsx")
            c.action("Run compare", lambda: compare(),
                     needs=lambda: missing({"old", "new", "dtcr"}))
            c.action("PreOrder list only", lambda: preorder(),
                     needs=lambda: missing({"old", "new"}),
                     icon="playlist_add_check", secondary=True)

        def show_compare(r: dict) -> None:
            with result.show():
                with c.kpi_strip():
                    for label, key in KPIS:
                        if key in r:
                            c.kpi(int(r[key]), label)
                ui.label("Every change is tagged with its DTCR in the workbook; "
                         "the PreOrder sheet lists what to order first.") \
                    .classes("sx-caption")
            with result.actions:
                c.download(r["output_file_name"], lambda: r["output_excel_bytes"])

        def show_preorder(r: dict) -> None:
            with result.show():
                c.note("info", "PreOrder list built from OLD and NEW only — "
                               "no DTCR tagging. Run the compare for the "
                               "change workbook.")
            with result.actions:
                c.download(r["output_file_name"], lambda: r["output_excel_bytes"])

        async def compare() -> None:
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
                show_compare(r)

        async def preorder() -> None:
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
                show_preorder(r)
