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
    my = st.text_input("Model Year (MY)", placeholder="e.g. 27")
    program = st.text_input("Program", placeholder="program code")
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
                with tempfile.TemporaryDirectory(prefix="splice_vbom_") as output_dir:
                    result = run_vbom_workflow(
                        my=my,
                        program=program,
                        source_type=source_type,
                        input_upload=input_upload,
                        complexity_uploads=complexity_uploads,
                        output_dir=Path(output_dir),
                    )
                    output_paths = [
                        ("Master complexity workbook", result.get("master_path")),
                        ("VIN / SalesCode matrix", result.get("vin_matrix_path")),
                        ("Harness selection workbook", result.get("selections_path")),
                        ("Selection review workbook", result.get("review_path")),
                    ]
                    archive_bytes = io.BytesIO()
                    generated_files: list[str] = []
                    with zipfile.ZipFile(
                        archive_bytes, "w", zipfile.ZIP_DEFLATED
                    ) as archive:
                        for _, path in output_paths:
                            if path is not None and Path(path).is_file():
                                safe_name = Path(path).name
                                archive.write(path, arcname=safe_name)
                                generated_files.append(safe_name)
                    st.session_state["vbom_archive_bytes"] = archive_bytes.getvalue()
                    st.session_state["vbom_generated_files"] = generated_files
            review_cases = result.get("review_case_count", 0)
            defe_name = result.get("defe_output_name", "the DEFE template")
            st.success("VBOM workbook bundle generated.")
            st.info(
                f"Open **Harness_Selection_Review** and resolve the "
                f"**{review_cases}** flagged selection(s). When Pending Reviews "
                f"reaches 0, use its **Generate DEFE Template** button to create "
                f"**{defe_name}**. The DEFE template is withheld until the review "
                f"is complete."
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure cleanly
            st.error(f"VBOM workflow failed: {exc}")

vbom_archive_bytes = st.session_state.get("vbom_archive_bytes")
if vbom_archive_bytes:
    st.subheader("Generated Files")
    for file_name in st.session_state.get("vbom_generated_files", []):
        st.write(f"- {file_name}")
    st.download_button(
        label="Download VBOM Bundle",
        data=vbom_archive_bytes,
        file_name="VBOM_Risk_Matrix_Bundle.zip",
        mime="application/zip",
        key="dl_vbom_bundle",
        width="stretch",
    )
