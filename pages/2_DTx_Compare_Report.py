from __future__ import annotations

from pathlib import Path
import sys
import tempfile

import streamlit as st

CURRENT_DIR = Path(__file__).resolve().parent
APP_DIR = CURRENT_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from splice.dtx_compare import (
    generate_dtx_change_report,
    launch_preorder_generation_tool,
    load_dtcr_report,
)
from feedback_system import FeedbackStore, render_feedback_widget


st.title("DTx Compare Report")
st.caption("Upload OLD and NEW DTx files to generate an engineering change workbook.")

feedback_store = FeedbackStore()
render_feedback_widget(workflow="DTx Compare Report", area="DTx Compare Report", store=feedback_store, key_prefix="dtx_feedback")

col_old, col_new, col_dtcr = st.columns(3)
with col_old:
    old_file = st.file_uploader("OLD DTx report", type=["xlsx", "xls", "xlsm"], key="dtx_old_file")
with col_new:
    new_file = st.file_uploader("NEW DTx report", type=["xlsx", "xls", "xlsm"], key="dtx_new_file")
with col_dtcr:
    dtcr_file = st.file_uploader(
        "DTCR report (optional)",
        type=["xlsx", "xls", "xlsm"],
        key="dtx_dtcr_file",
        help="If provided, every change is tagged with its DTCR# via the Device Transmittal mapping.",
    )

if old_file is None or new_file is None:
    st.info("Upload both OLD and NEW DTx reports to continue. Optionally add a DTCR report to tag changes with DTCR#.")
    st.stop()

st.subheader("PreOrder Generation List")
st.caption("Generate the PreOrder workbook directly for the selected DTx reports.")

if st.button("Generate PreOrder Generation List", type="secondary"):
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="dtx_preorder_", dir=tempfile.gettempdir()))
        old_temp_path = temp_dir / old_file.name
        new_temp_path = temp_dir / new_file.name
        old_temp_path.write_bytes(old_file.getvalue())
        new_temp_path.write_bytes(new_file.getvalue())

        with st.spinner("Generating PreOrder workbook..."):
            preorder_result = launch_preorder_generation_tool(
                old_file_path=old_temp_path,
                new_file_path=new_temp_path,
            )
        st.session_state["preorder_generation_result"] = preorder_result
        st.success("PreOrder workbook generated.")
    except Exception as exc:
        st.error(f"Unable to generate the PreOrder workbook: {exc}")

preorder_result = st.session_state.get("preorder_generation_result")
if preorder_result is not None:
    st.dataframe(preorder_result["summary_df"], use_container_width=True)
    st.download_button(
        label="Download PreOrder Workbook",
        data=preorder_result["output_excel_bytes"],
        file_name=preorder_result["output_file_name"],
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

if st.button("Generate Compare Report", type="primary"):
    try:
        dtcr_df = None
        if dtcr_file is not None:
            dtcr_df = load_dtcr_report(dtcr_file.getvalue(), dtcr_file.name)
        with st.spinner("Comparing reports and building workbook..."):
            result = generate_dtx_change_report(
                old_file_bytes=old_file.getvalue(),
                new_file_bytes=new_file.getvalue(),
                old_file_name=old_file.name,
                new_file_name=new_file.name,
                dtcr_df=dtcr_df,
            )
        st.session_state["dtx_compare_result"] = result
        st.session_state["dtx_old_name"] = old_file.name
        st.session_state["dtx_new_name"] = new_file.name
    except Exception as exc:
        st.error(f"DTx comparison failed: {exc}")

result = st.session_state.get("dtx_compare_result")
if result is None:
    st.stop()

st.success("Comparison complete.")

metric_cols = st.columns(5)
metric_cols[0].metric("Added CNUMs", int(result["added_cnum_count"]))
metric_cols[1].metric("Removed CNUMs", int(result["removed_cnum_count"]))
metric_cols[2].metric("Added Circuits", int(result["added_circuit_count"]))
metric_cols[3].metric("Removed Circuits", int(result["removed_circuit_count"]))
metric_cols[4].metric("Modified Circuits", int(result["modified_circuit_count"]))

st.subheader("Detected Layout")
layout_left, layout_right = st.columns(2)
old_layout = result["old_layout"]
new_layout = result["new_layout"]
layout_left.info(f"OLD: sheet '{old_layout.sheet_name}', header row {old_layout.header_row + 1}")
layout_right.info(f"NEW: sheet '{new_layout.sheet_name}', header row {new_layout.header_row + 1}")

st.subheader("Changes by Harness Family")
family_summary_df = result.get("harness_family_summary_df")
all_changes_df = result.get("all_changes_df")

if family_summary_df is not None and not family_summary_df.empty:
    st.dataframe(family_summary_df, use_container_width=True)
    st.bar_chart(
        family_summary_df.set_index("Harness Family")[
            ["Added Circuits", "Removed Circuits", "Modified Circuits"]
        ]
    )

if all_changes_df is not None and not all_changes_df.empty:
    st.subheader("All Changes")
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        family_filter = st.multiselect(
            "Filter by Harness Family",
            options=sorted(all_changes_df["Harness Family"].unique()),
            key="dtx_family_filter",
        )
    with filter_col2:
        type_filter = st.multiselect(
            "Filter by Change Type",
            options=list(all_changes_df["Change Type"].unique()),
            key="dtx_type_filter",
        )
    filtered = all_changes_df
    if family_filter:
        filtered = filtered[filtered["Harness Family"].isin(family_filter)]
    if type_filter:
        filtered = filtered[filtered["Change Type"].isin(type_filter)]
    st.caption(f"{len(filtered):,} of {len(all_changes_df):,} changes shown")
    st.dataframe(filtered, use_container_width=True)

st.subheader("Preview Tables")
with st.expander("Added Circuits", expanded=False):
    st.dataframe(result["added_circuits_df"], use_container_width=True)
with st.expander("Removed Circuits", expanded=False):
    st.dataframe(result["removed_circuits_df"], use_container_width=True)
with st.expander("Modified Circuits", expanded=False):
    st.dataframe(result["modified_circuits_df"], use_container_width=True)
with st.expander("CNUM Summary", expanded=False):
    st.dataframe(result["cnum_summary_df"], use_container_width=True)
with st.expander("Field Change Frequency", expanded=False):
    st.dataframe(result["field_change_frequency_df"], use_container_width=True)

download_col1, download_col2 = st.columns(2)
with download_col1:
    st.download_button(
        label="Download DTx Compare Workbook",
        data=result["output_excel_bytes"],
        file_name=result["output_file_name"],
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

dtcr_matching_bytes = result.get("dtcr_matching_bytes")
if dtcr_matching_bytes is not None:
    with download_col2:
        st.download_button(
            label="Download DTCR Matching Report",
            data=dtcr_matching_bytes,
            file_name=result.get("dtcr_matching_file_name", "DTCR_Matching_Report.xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with st.expander("DTCR Matching Report (built from BOTH DTx reports)", expanded=False):
        matching_df = result.get("dtcr_matching_df")
        if matching_df is not None:
            matched = int((matching_df["Match Method"] != "No Match").sum())
            st.caption(f"{matched} of {len(matching_df)} DTCRs matched to a CNUM / Harness Family")
            st.dataframe(matching_df, use_container_width=True)
