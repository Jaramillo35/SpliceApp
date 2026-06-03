from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st

CURRENT_DIR = Path(__file__).resolve().parent
APP_DIR = CURRENT_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from dtx_compare_engine import generate_dtx_change_report


st.set_page_config(page_title="DTx Compare Report", layout="wide")

st.title("DTx Compare Report")
st.caption("Upload OLD and NEW DTx files to generate an engineering change workbook.")

col_old, col_new = st.columns(2)
with col_old:
    old_file = st.file_uploader("OLD DTx report", type=["xlsx", "xls", "xlsm"], key="dtx_old_file")
with col_new:
    new_file = st.file_uploader("NEW DTx report", type=["xlsx", "xls", "xlsm"], key="dtx_new_file")

if old_file is None or new_file is None:
    st.info("Upload both OLD and NEW DTx reports to continue.")
    st.stop()

if st.button("Generate Compare Report", type="primary"):
    try:
        with st.spinner("Comparing reports and building workbook..."):
            result = generate_dtx_change_report(
                old_file_bytes=old_file.getvalue(),
                new_file_bytes=new_file.getvalue(),
                old_file_name=old_file.name,
                new_file_name=new_file.name,
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

st.subheader("Preview Tables")
with st.expander("Added Circuits", expanded=False):
    st.dataframe(result["added_circuits_df"], use_container_width=True)
with st.expander("Removed Circuits", expanded=False):
    st.dataframe(result["removed_circuits_df"], use_container_width=True)
with st.expander("Modified Circuits", expanded=True):
    st.dataframe(result["modified_circuits_df"], use_container_width=True)
with st.expander("CNUM Summary", expanded=False):
    st.dataframe(result["cnum_summary_df"], use_container_width=True)
with st.expander("Field Change Frequency", expanded=False):
    st.dataframe(result["field_change_frequency_df"], use_container_width=True)

st.download_button(
    label="Download DTx Compare Workbook",
    data=result["output_excel_bytes"],
    file_name=result["output_file_name"],
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
