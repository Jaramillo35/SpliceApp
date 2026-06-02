from __future__ import annotations

from pathlib import Path
import tempfile

import streamlit as st

from wiring_harness_processor import (
    generate_expression_for_selected_pns,
    get_selected_harness_pns,
    run_analysis,
    run_analysis_from_option_df,
    simplify_expression_for_display,
    validate_generated_expression,
)


st.set_page_config(page_title="Wiring Harness Splice Generator", layout="wide")

st.title("⚡ Wiring Harness Splice Generator")
st.caption("✨ Generate harness print-ready direct connections, splices, configuration groups, and validation reports.")

uploaded_file = st.file_uploader("Upload Excel file (Complexity + OptionPerCkt)", type=["xlsx", "xls"])

if uploaded_file is None:
    st.info("Upload Input.xlsx (or equivalent) to begin analysis.")
    st.stop()

with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as temp_file:
    temp_file.write(uploaded_file.getbuffer())
    temp_path = temp_file.name

try:
    result = run_analysis(temp_path)
except Exception as exc:
    st.error(f"Analysis failed: {exc}")
    st.stop()

if "analysis_result" not in st.session_state:
    st.session_state["analysis_result"] = result
else:
    # Reset session result when a different file is uploaded
    prev_name = st.session_state.get("uploaded_file_name")
    if prev_name != uploaded_file.name:
        st.session_state["analysis_result"] = result

st.session_state["uploaded_file_name"] = uploaded_file.name
result = st.session_state["analysis_result"]

st.subheader("📊 Input Previews")
left, right = st.columns(2)
with left:
    st.markdown("**📋 Complexity Matrix (normalized)**")
    st.dataframe(result["harness_code_map_df"], use_container_width=True)
with right:
    st.markdown("**📋 OptionPerCircuit (normalized)**")
    st.dataframe(result["option_df"], use_container_width=True)

st.subheader("⚙️ Generated Configurations")
st.dataframe(result["configurations_df"], use_container_width=True)

st.subheader("🔗 Generated Connections")
# Group connections by circuit and configuration
conns_df = result["generated_connections_df"]
configs_df = result["configurations_df"]

# Create lookup for configuration details
config_lookup = {}
for _, cfg in configs_df.iterrows():
    key = (cfg["Circuit Name"], cfg["Configuration ID"])
    config_lookup[key] = {
        "topology_type": cfg["Topology Type"],
        "target_harness_pns": cfg["Target Harness PNs"],
    }

# Group by circuit and configuration
for (circuit, config_id), group in conns_df.groupby(["Circuit Name", "Configuration"], sort=False):
    cfg_details = config_lookup.get((circuit, config_id), {})
    topology = cfg_details.get("topology_type", "Unknown")
    target_pns = cfg_details.get("target_harness_pns", "")
    
    # Display circuit heading if this is the first config for this circuit
    if config_id == conns_df[conns_df["Circuit Name"] == circuit]["Configuration"].iloc[0]:
        st.markdown(f"### 📌 Circuit {circuit}")
    
    # Topology icon
    topo_icon = "📍" if topology == "Direct" else "🔀"
    st.markdown(f"**{topo_icon} Configuration {config_id} — {topology}**")
    
    # Summary info
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"🔗 **Connections:** {len(group)}")
    with col2:
        st.markdown(f"🏗️ **Topology:** {topology}")
    with col3:
        st.markdown(f"📦 **Target PNs:** {target_pns}")
    
    st.dataframe(group, use_container_width=True)
    st.markdown("---")

st.subheader("📊 Harness Print Matrix")
st.markdown("Engineering applicability matrix showing which connections apply to each Harness PN:")
st.dataframe(result["harness_print_matrix_df"], use_container_width=True)

st.subheader("🧩 Interactive Sales Code Generator")
st.markdown("Select a matrix row, toggle Harness PN checkboxes, then generate a valid sales code expression.")

matrix_df = result["harness_print_matrix_df"].copy()
fixed_cols = ["Device ID", "Connector No", "Device Name", "Pin", "Circuit", "Sales Code"]
harness_cols = [col for col in matrix_df.columns if col not in fixed_cols]

if matrix_df.empty or not harness_cols:
    st.info("No harness matrix rows available for interactive selection.")
else:
    selectable_rows = [
        f"{idx}: {row['Connector No']} | {row['Device Name']} | Pin {row['Pin']} | {row['Circuit']}"
        for idx, row in matrix_df.iterrows()
    ]
    selected_row_label = st.selectbox("Select Row", selectable_rows, key="interactive_row_selector")
    selected_row_idx = int(selected_row_label.split(":", 1)[0])

    selected_row = matrix_df.loc[[selected_row_idx], fixed_cols + harness_cols].copy()
    row_header = selected_row.iloc[0]
    st.markdown(
        f"**Selected:** Connector {row_header['Connector No']} | Device {row_header['Device Name']} | "
        f"Pin {row_header['Pin']} | Circuit {row_header['Circuit']}"
    )

    edit_df = selected_row.copy()
    for pn in harness_cols:
        edit_df[pn] = edit_df[pn].astype(str).eq("☑")

    edited_df = st.data_editor(
        edit_df,
        column_config={pn: st.column_config.CheckboxColumn(pn) for pn in harness_cols},
        use_container_width=True,
        num_rows="fixed",
        key=f"interactive_editor_{selected_row_idx}",
    )

    col_gen, col_apply = st.columns(2)
    with col_gen:
        if st.button("Generate Sales Code", key="btn_generate_sales_code"):
            selected_by_row = get_selected_harness_pns(edited_df)
            selected_pns = selected_by_row.get(selected_row_idx, [])
            expr = generate_expression_for_selected_pns(selected_pns, result["harness_code_map"])

            if not expr:
                st.session_state["interactive_generated_expr"] = None
                st.session_state["interactive_expr_valid"] = False
                st.error("Combination not valid with available salescodes")
            else:
                valid = validate_generated_expression(expr, selected_pns, result["harness_code_map"])
                if not valid:
                    st.session_state["interactive_generated_expr"] = None
                    st.session_state["interactive_expr_valid"] = False
                    st.error("Combination not valid with available salescodes")
                else:
                    display_expr = simplify_expression_for_display(expr)
                    st.session_state["interactive_generated_expr"] = display_expr
                    st.session_state["interactive_expr_valid"] = True
                    st.session_state["interactive_target_row"] = selected_row_idx
                    st.success(f"Generated Sales Code: {display_expr}")

    with col_apply:
        can_apply = (
            st.session_state.get("interactive_expr_valid", False)
            and st.session_state.get("interactive_target_row") == selected_row_idx
        )
        if st.button("Apply Sales Code to Row", disabled=not can_apply, key="btn_apply_sales_code"):
            generated_expr = st.session_state.get("interactive_generated_expr", "")
            if not generated_expr:
                st.error("No valid generated sales code to apply.")
            else:
                target_row = matrix_df.loc[selected_row_idx]
                target_cnum = str(target_row["Connector No"]).strip()
                target_pin = str(target_row["Pin"]).strip()
                target_circuit = str(target_row["Circuit"]).strip()

                updated_option_df = result["option_df"].copy()
                match_mask = (
                    updated_option_df["CNUM"].astype(str).str.strip().eq(target_cnum)
                    & updated_option_df["Pin"].astype(str).str.strip().eq(target_pin)
                    & updated_option_df["Circuit"].astype(str).str.strip().eq(target_circuit)
                )

                if not match_mask.any():
                    st.error("Could not map selected row back to OptionPerCircuit row.")
                else:
                    updated_option_df.loc[match_mask, "Sales Code"] = generated_expr
                    refreshed = run_analysis_from_option_df(temp_path, updated_option_df)
                    st.session_state["analysis_result"] = refreshed
                    st.success("Sales code applied. Configurations and validation refreshed.")
                    st.rerun()

st.subheader("✅ Validation Report")
st.dataframe(result["validation_report_df"], use_container_width=True)

st.download_button(
    label="📥 Download Output Excel",
    data=result["output_excel_bytes"],
    file_name="Wiring_Harness_Output.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
