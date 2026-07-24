from __future__ import annotations

import io
import sys
import tempfile
import zipfile
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from feedback_system import FeedbackStore, render_feedback_widget
from splice.vbom import run_vbom_workflow

st.title("VBOM Risk Matrix")
st.caption(
    "Upload a DoAll or BuildSpec file and one or more harness complexity files to "
    "generate the VBOM workbook bundle used by the desktop workflow."
)

feedback_store = FeedbackStore()
render_feedback_widget(
    workflow="VBOM Risk Matrix",
    area="VBOM Risk Matrix",
    store=feedback_store,
    key_prefix="vbom_feedback",
)

with st.form("vbom_streamlit_form"):
    my = st.text_input("Model Year (MY)", value="27")
    program = st.text_input("Program", value="RU")
    source_type = st.radio("Input source", ["DoAll", "BuildSpec"], horizontal=True)
    input_upload = st.file_uploader(
        "DoAll / BuildSpec file",
        type=["xlsx", "xls", "xlsm", "csv"],
        key="vbom_input_file",
    )
    complexity_uploads = st.file_uploader(
        "Harness Complexity files",
        type=["xlsx", "xls", "xlsm"],
        accept_multiple_files=True,
        key="vbom_complexity_files",
    )
    generate_clicked = st.form_submit_button("Generate VBOM Bundle", type="primary")

if generate_clicked:
    if input_upload is None or not complexity_uploads:
        st.error("Please upload an input file and at least one harness complexity file.")
    else:
        try:
            with st.spinner("Generating VBOM outputs..."):
                result = run_vbom_workflow(
                    my=my,
                    program=program,
                    source_type=source_type,
                    input_upload=input_upload,
                    complexity_uploads=complexity_uploads,
                    output_dir=Path(tempfile.gettempdir()) / "splice_vbom_outputs",
                )
            st.session_state["vbom_result"] = result
            st.success("VBOM workbook bundle generated.")
        except Exception as exc:  # noqa: BLE001 - surface any failure cleanly
            st.error(f"VBOM workflow failed: {exc}")

vbom_result = st.session_state.get("vbom_result")
if vbom_result is not None:
    st.subheader("Generated Files")
    output_paths = [
        ("Master complexity workbook", vbom_result.get("master_path")),
        ("VIN / SalesCode matrix", vbom_result.get("vin_matrix_path")),
        ("Harness selection workbook", vbom_result.get("selections_path")),
        ("Formatted template", vbom_result.get("formatted_template_path")),
    ]
    for label, path in output_paths:
        if path is not None and Path(path).exists():
            st.write(f"- {label}: {Path(path).name}")

    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
        for _, path in output_paths:
            if path is not None and Path(path).exists():
                archive.write(path, arcname=Path(path).name)
    archive_bytes.seek(0)
    st.download_button(
        label="Download VBOM Bundle",
        data=archive_bytes.getvalue(),
        file_name="VBOM_Risk_Matrix_Bundle.zip",
        mime="application/zip",
        key="dl_vbom_bundle",
        use_container_width=True,
    )
