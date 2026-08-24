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
    state: dict = {"input": None, "complexity": [], "zip": None,
                   "files": [], "note": ""}

    with c.frame("VBOM Risk Matrix",
                 "DoAll / BuildSpec + harness complexity files → the VBOM "
                 "workbook bundle."):
        with c.card("Inputs"):
            with ui.row().classes("w-full gap-4 flex-wrap items-end"):
                my = ui.input("Model year", value="26").classes("w-28")
                program = ui.input("Program", value="RU").classes("w-28")
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
            with c.card("Generated files"):
                for name in state["files"]:
                    ui.label(f"• {name}").classes("text-sm sx-muted")
                if state["note"]:
                    ui.label(state["note"]).classes("text-sm") \
                        .style("color:#c98500")
                c.download_button("VBOM_Risk_Matrix_Bundle.zip", lambda: state["zip"])

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
                    note = ""
                    if result.get("review_case_count"):
                        note = (f"Open Harness_Selection_Review and resolve the "
                                f"{result['review_case_count']} flagged selection(s); "
                                f"the DEFE template "
                                f"({result.get('defe_output_name', 'DEFE')}) is "
                                "withheld until Pending Reviews reaches 0.")
                    return buf.getvalue(), names, note

            r = await c.run_engine(work, running="Running the VBOM workflow…",
                                   done="VBOM bundle ready")
            if r is not None:
                state["zip"], state["files"], state["note"] = r
                render_result.refresh()
