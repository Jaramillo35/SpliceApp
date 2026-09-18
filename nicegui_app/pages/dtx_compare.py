"""DTx Compare — NiceGUI page over the enhanced compare + preorder engines.

Archetype A (converter): inputs panel with one gated primary, result panel
that exists before the run.

The page has one job and two side outputs, and the layout says so: the two
DTx exports are required and the DTCR report is optional, grouped and
labelled as such; "Run compare" is the primary; the DTCR Matching Report on
its own and the PreOrder list sit under "Other outputs". Every result opens
with a label naming what ran, so a matching-only result never reads as a
compare that lost its numbers, and the files are listed as deliverables —
what each is and who it is for — because two workbooks with similar names
read as duplicates unless each states its job.

Captions never contain a button's label: the simulated user finds elements
by text, and a caption that names a button swallows the click.
"""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme

REQUIRED = (("OLD DTx", "old"), ("NEW DTx", "new"), ("DTCR report", "dtcr"))
#: what ran, said at the top of every result — never a button's label
RAN_TAGGED = "Change compare — tagged by DTCR"
RAN_UNTAGGED = "Change compare — no DTCR report"
RAN_MATCHING = "DTCR matching report"
RAN_PREORDER = "PreOrder list"

WORKBOOK_TAGGED = ("Every added, removed and modified circuit and connector, each "
                   "tagged with its DTCR. Holds the DTCR Matching and PreOrder sheets.")
WORKBOOK_UNTAGGED = ("Every added, removed and modified circuit and connector. The "
                     "DTCR# column is empty and there is no DTCR Matching sheet.")
MATCHING_PURPOSE = ("For the SECR Database: file it in the DTCR library under its "
                    "programme, model year and phase.")
KPIS = (("Added CNUMs", "added_cnum_count"), ("Removed CNUMs", "removed_cnum_count"),
        ("Added circuits", "added_circuit_count"),
        ("Removed circuits", "removed_circuit_count"),
        ("Modified circuits", "modified_circuit_count"))


@ui.page("/dtx-compare")
def page() -> None:
    state: dict = {"old": None, "new": None, "dtcr": None}

    with c.frame("DTx Compare",
                 "OLD vs NEW DTx → the change workbook; with a DTCR report, every "
                 "change is tagged and the SECR Database gets its matching report."):
        inputs, result = c.converter(
            "Drop the OLD and NEW DTx exports. The compare lists every added, "
            "removed and changed circuit and connector and builds the change "
            "workbook. Add the DTCR report to tag each change with its DTCR, "
            "get the DTCR Matching sheet in the workbook, and download the "
            "DTCR Matching Report as its own file for the SECR Database.",
            inputs_caption="Two exports are enough to compare.")

        def missing(keys):
            return [label for label, key in REQUIRED if key in keys and not state[key]]

        with inputs:
            ui.label("Required").classes("sx-eyebrow")
            c.upload_row("OLD DTx report (.xls)",
                         lambda n, b: state.update(old=(n, b)), accept=".xls,.xlsx")
            c.upload_row("NEW DTx report (.xls)",
                         lambda n, b: state.update(new=(n, b)), accept=".xls,.xlsx")
            ui.label("Optional").classes("sx-eyebrow mt-1")
            c.upload_row("DTCR report (.xls)",
                         lambda n, b: state.update(dtcr=(n, b)), accept=".xls,.xlsx")
            ui.label("Adds the DTCR number to every change, the matching sheet in "
                     "the workbook, and the matching report for the SECR Database.") \
                .classes("sx-caption -mt-1")
            c.action("Run compare", lambda: compare(),
                     needs=lambda: missing({"old", "new"}))
            ui.separator().classes("my-1")
            ui.label("Other outputs").classes("sx-eyebrow")
            c.action("DTCR Matching only", lambda: matching(),
                     needs=lambda: missing({"old", "new", "dtcr"}),
                     icon="link", secondary=True)
            c.action("PreOrder list only", lambda: preorder(),
                     needs=lambda: missing({"old", "new"}),
                     icon="playlist_add_check", secondary=True)

        def ran(label: str) -> None:
            """What this result is, before anything else in it."""
            with ui.row().classes("items-center gap-2"):
                ui.label("This run").classes("sx-eyebrow")
                c.chip("info", label)

        def deliverable(title: str, purpose: str, filename: str, getter, *,
                        dress: bool = True) -> None:
            """One file: what it is, who it is for, and its download."""
            with ui.row().classes("w-full items-center justify-between gap-3 "
                                  "flex-wrap rounded px-3 py-2") \
                    .style(f"background:{theme.SURFACE_2};border:1px solid {theme.LINE}"):
                with ui.column().classes("gap-0 min-w-0 grow basis-64"):
                    ui.label(title).classes("text-sm font-semibold")
                    ui.label(purpose).classes("sx-caption")
                c.download(filename, getter, dress=dress)

        def show_compare(r: dict) -> None:
            tagged = r.get("dtcr_matching_df") is not None
            with result.show():
                ran(RAN_TAGGED if tagged else RAN_UNTAGGED)
                with c.kpi_strip():
                    for label, key in KPIS:
                        if key in r:
                            c.kpi(int(r[key]), label)
                if not tagged:
                    c.note("info", "Built without a DTCR report, so no change carries "
                                   "a DTCR number. Add the report under Optional and "
                                   "run again to tag them.")
                ui.label("Files").classes("sx-eyebrow mt-1")
                deliverable("Change workbook",
                            WORKBOOK_TAGGED if tagged else WORKBOOK_UNTAGGED,
                            r["output_file_name"], lambda: r["output_excel_bytes"])
                if tagged and r.get("dtcr_matching_bytes"):
                    # another tool's input: handed over exactly as the engine wrote it
                    deliverable("DTCR Matching Report", MATCHING_PURPOSE,
                                r["dtcr_matching_file_name"],
                                lambda: r["dtcr_matching_bytes"], dress=False)

        def show_matching(r: dict) -> None:
            with result.show():
                ran(RAN_MATCHING)
                df = r["dtcr_matching_df"]
                matched = int((df["Match Method"] != "No Match").sum()) \
                    if "Match Method" in df.columns else 0
                unmatched = len(df) - matched
                with c.kpi_strip():
                    c.kpi(len(df), "DTCRs")
                    c.kpi(matched, "Matched to a harness family", "ok" if matched else None)
                    c.kpi(unmatched, "Unmatched", "review" if unmatched else "ok")
                ui.label("Files").classes("sx-eyebrow mt-1")
                deliverable("DTCR Matching Report", MATCHING_PURPOSE,
                            r["output_file_name"], lambda: r["output_excel_bytes"],
                            dress=False)

        def show_preorder(r: dict) -> None:
            with result.show():
                ran(RAN_PREORDER)
                c.note("info", "Built from OLD and NEW only — no DTCR tagging. The "
                               "change workbook comes from the compare.")
                ui.label("Files").classes("sx-eyebrow mt-1")
                deliverable("PreOrder list", "Connector changes to order first.",
                            r["output_file_name"], lambda: r["output_excel_bytes"])

        def dtcr_frame():
            from splice.dtx_compare.engine import load_dtcr_report
            return load_dtcr_report(state["dtcr"][1], state["dtcr"][0]) \
                if state["dtcr"] else None

        async def compare() -> None:
            def work():
                from splice.dtx_compare.enhanced_report import generate_enhanced_dtx_report
                return generate_enhanced_dtx_report(
                    state["old"][1], state["new"][1],
                    state["old"][0], state["new"][0], dtcr_frame())

            r = await c.run_engine(work, running="Comparing reports and building the workbook…",
                                   done="Compare workbook ready")
            if r is not None:
                show_compare(r)

        async def matching() -> None:
            def work():
                from splice.dtx_compare.engine import generate_dtcr_matching_report
                return generate_dtcr_matching_report(
                    state["old"][1], state["new"][1],
                    state["old"][0], state["new"][0], dtcr_frame())

            r = await c.run_engine(work, running="Matching DTCRs to harness families…",
                                   done="DTCR Matching Report ready")
            if r is not None:
                show_matching(r)

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
