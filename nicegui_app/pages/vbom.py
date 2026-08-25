"""VBOM Risk Matrix — NiceGUI page over splice.vbom.run_vbom_workflow."""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from nicegui import ui

from nicegui_app import components as c


class _Upload:
    """Adapter with the .name/.getbuffer() surface the workflow expects."""

    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getbuffer(self):
        return self._data

    def getvalue(self) -> bytes:
        return self._data

    def read(self) -> bytes:
        return self._data


@ui.page("/vbom")
def page() -> None:
    from splice.vbom import review as review_engine

    state: dict = {"input": None, "complexity": [], "zip": None,
                   "files": [], "result": None,
                   "resolutions": {}, "notes": {}, "defe": None}

    with c.frame("VBOM Risk Matrix",
                 "DoAll / BuildSpec + harness complexity files → the VBOM "
                 "workbook bundle."):
        with c.card("Inputs"):
            with ui.row().classes("w-full gap-4 flex-wrap items-end"):
                my = ui.input("Model year", placeholder="e.g. 26").classes("w-28")
                program = ui.input("Program", placeholder="program code").classes("w-28")
                source = ui.select(["DoAll", "BuildSpec"], value="DoAll",
                                   label="Input type").classes("w-36")
            with ui.row().classes("w-full gap-4 flex-wrap"):
                c.upload_zone("DoAll / BuildSpec file",
                              lambda n, b: state.update(input=_Upload(n, b)),
                              accept=".xlsx,.xlsm,.xls")
                c.upload_zone("Harness complexity file(s)",
                              lambda n, b: state["complexity"].append(_Upload(n, b)),
                              accept=".xlsx,.xlsm,.xls", multiple=True)
            ui.button("Generate VBOM bundle", icon="play_arrow",
                      on_click=lambda: generate()).props("unelevated")

        @ui.refreshable
        def render_result() -> None:
            if not state["zip"]:
                return
            with c.card("Generated files",
                        "The bundle includes the macro-enabled review workbook — "
                        "resolve in Excel there, or right here below."):
                for name in state["files"]:
                    ui.label(f"• {name}").classes("text-sm sx-muted")
                c.download_button("VBOM_Risk_Matrix_Bundle.zip", lambda: state["zip"])
            review_workbench()

        def review_workbench() -> None:
            r = state["result"]
            review_df = r["review_df"]
            total = len(review_df)
            resolved = len(state["resolutions"])

            with c.card("Review gate",
                        "The DEFE template is withheld until every flagged "
                        "selection has a decision — same rule as the Excel "
                        "workbook's macro."):
                if total == 0:
                    c.chip("ok", "No uncertain selections — the DEFE template "
                                 "is ready to generate")
                else:
                    with ui.row().classes("w-full h-2 rounded-full overflow-hidden gap-0"):
                        ok, open_c = c.theme.STATUS["ok"], c.theme.STATUS["high"]
                        if resolved:
                            ui.element("div").style(
                                f"background:{ok};width:{resolved / total * 100:.1f}%")
                        ui.element("div").style(
                            f"background:{open_c};width:{(total - resolved) / total * 100:.1f}%")
                    ui.label(f"{resolved} of {total} flagged selection(s) resolved") \
                        .classes("text-xs sx-muted")
                    with ui.row().classes("gap-2 flex-wrap"):
                        for reason, n in review_engine.reason_counts(review_df).items():
                            c.chip("high", f"{n} · {reason}")
                    for _, case in review_df.iterrows():
                        review_case(case)

                done = total == 0 or resolved == total
                with ui.row().classes("items-center gap-3 mt-2 flex-wrap"):
                    ui.button(f"Generate {r['defe_output_name']}",
                              icon="assignment_turned_in",
                              on_click=lambda: make_defe()) \
                        .props("unelevated").set_enabled(done)
                    if not done:
                        c.chip("high", f"{total - resolved} selection(s) still open")
                    if state["defe"]:
                        c.download_button(state["defe"][0], lambda: state["defe"][1])

        def review_case(case) -> None:
            rid = str(case["ReviewID"])
            resolved_pn = state["resolutions"].get(rid)
            with ui.expansion().classes("w-full").props("dense") as exp:
                with exp.add_slot("header"):
                    with ui.row().classes("items-center gap-3 w-full py-1 flex-wrap"):
                        c.chip("ok" if resolved_pn else "high",
                               resolved_pn or "open")
                        ui.label(f"{case['VIN']}").classes("text-sm sx-mono")
                        ui.label(str(case["HarnessFamily"])) \
                            .classes("text-sm font-semibold")
                        ui.label(str(case["ReviewReason"])) \
                            .classes("text-xs sx-muted")
                for label, key in [("Engine recommendation", "EngineRecommendation"),
                                   ("Required codes", "RequiredSalesCodes"),
                                   ("Missing codes", "MissingSalesCodes"),
                                   ("Extra codes", "ExtraSalesCodes"),
                                   ("Giveaway", "Giveaway")]:
                    value = str(case.get(key) or "").strip()
                    if value:
                        with ui.row().classes("gap-2"):
                            ui.label(label).classes("text-xs sx-muted w-40")
                            ui.label(value).classes("text-xs sx-mono")
                details = str(case.get("CandidateDetails") or "")
                if details:
                    ui.label(details).classes(
                        "text-xs sx-mono p-2 rounded w-full whitespace-pre-line") \
                        .style(f"background:{c.theme.CANVAS}")
                options = review_engine.allowed_pns(case)
                pn_sel = ui.select(options,
                                   value=resolved_pn if resolved_pn in options
                                   else (case["EngineRecommendation"]
                                         if case["EngineRecommendation"] in options
                                         else None),
                                   label="Resolved PN").classes("w-64") \
                    .props("dense")
                note_in = ui.input("Reviewer note",
                                   value=state["notes"].get(rid, "")) \
                    .classes("w-full").props("dense")

                def resolve(rid=rid, pn_sel=pn_sel, note_in=note_in) -> None:
                    if not pn_sel.value:
                        ui.notify("Pick a PN first", type="warning")
                        return
                    state["resolutions"][rid] = pn_sel.value
                    state["notes"][rid] = note_in.value or ""
                    state["defe"] = None  # decisions changed; regenerate
                    render_result.refresh()

                def reopen(rid=rid) -> None:
                    state["resolutions"].pop(rid, None)
                    state["defe"] = None
                    render_result.refresh()

                with ui.row().classes("gap-2"):
                    ui.button("Resolve", icon="check", on_click=resolve) \
                        .props("outline dense")
                    if resolved_pn:
                        ui.button("Reopen", icon="undo", on_click=reopen) \
                            .props("flat dense")

        async def make_defe() -> None:
            r = state["result"]

            def work():
                resolved_df = review_engine.apply_resolutions(
                    r["selections_df"], state["resolutions"])
                return review_engine.generate_defe(
                    r["my"], r["program"], resolved_df, r["vin_matrix_df"])

            out = await c.run_engine(work, running="Generating the DEFE template…",
                                     done="DEFE template ready")
            if out is not None:
                state["defe"] = out
                render_result.refresh()

        render_result()

        async def generate() -> None:
            if not (state["input"] and state["complexity"]):
                ui.notify("Load the input file and at least one complexity file",
                          type="warning")
                return

            def work():
                from splice.vbom import run_vbom_workflow
                with tempfile.TemporaryDirectory(prefix="ng_vbom_") as td:
                    result = run_vbom_workflow(
                        my=my.value, program=program.value,
                        source_type=source.value,
                        input_upload=state["input"],
                        complexity_uploads=list(state["complexity"]),
                        output_dir=Path(td),
                    )
                    buf, names = io.BytesIO(), []
                    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                        for key in ("master_path", "vin_matrix_path",
                                    "selections_path", "review_path"):
                            path = result.get(key)
                            if path and Path(path).is_file():
                                zf.write(path, arcname=Path(path).name)
                                names.append(Path(path).name)
                    return result, buf.getvalue(), names

            out = await c.run_engine(work, running="Running the VBOM workflow…",
                                     done="VBOM bundle ready")
            if out is not None:
                state["result"], state["zip"], state["files"] = out
                state["resolutions"], state["notes"], state["defe"] = {}, {}, None
                render_result.refresh()
