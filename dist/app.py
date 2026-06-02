from __future__ import annotations

from pathlib import Path
import tempfile

import pandas as pd
import streamlit as st

from wiring_harness_processor import (
    evaluate_expression_against_all_pns,
    generate_sales_code_expression,
    generate_expression_for_selected_pns,
    get_candidate_codes_from_option_df,
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
st.markdown("Select circuit/row from the second sheet, edit Sales Code text, and visualize PN applicability from first-sheet rules.")

option_df = result["option_df"].copy()
circuits = sorted(option_df["Circuit"].dropna().astype(str).str.strip().unique().tolist())

if not circuits:
    st.info("No circuits available in the second sheet (OptionPerCkt).")
else:
    selected_circuit = st.selectbox("Circuit", circuits, key="interactive_circuit_selector")
    circuit_rows = option_df[option_df["Circuit"].astype(str).str.strip() == selected_circuit].copy()

    row_labels = [
        f"{idx}: {row['CNUM']} | Pin {row['Pin']} | SalesCode={row['Sales Code']}"
        for idx, row in circuit_rows.iterrows()
    ]
    selected_row_label = st.selectbox("Row", row_labels, key="interactive_row_selector")
    selected_row_idx = int(selected_row_label.split(":", 1)[0])
    selected_row = option_df.loc[selected_row_idx]

    sales_code_input = st.text_input(
        "Sales Code",
        value=str(selected_row["Sales Code"]),
        key=f"interactive_sales_code_input_{selected_row_idx}",
    )

    harness_cols = sorted({k.split("__")[0] for k in result["harness_code_map"].keys()})
    fixed_cols = ["Device ID", "Connector No", "Device Name", "Pin", "Circuit", "Sales Code"]

    matched_pns: list[str] = []
    expression_valid = True
    validation_message = ""
    if sales_code_input.strip():
        try:
            matched_pns = evaluate_expression_against_all_pns(sales_code_input.strip(), result["harness_code_map"])
        except Exception:
            expression_valid = False
            validation_message = "Combination not valid with available salescodes"

    visualize_row = {
        "Device ID": "",
        "Connector No": str(selected_row["CNUM"]),
        "Device Name": "Interactive_Row",
        "Pin": str(selected_row["Pin"]),
        "Circuit": selected_circuit,
        "Sales Code": sales_code_input.strip(),
    }
    for pn in harness_cols:
        visualize_row[pn] = pn in matched_pns

    st.markdown("**PN Applicability Grid**")
    edited_df = st.data_editor(
        pd.DataFrame([visualize_row]),
        column_config={pn: st.column_config.CheckboxColumn(pn) for pn in harness_cols},
        use_container_width=True,
        num_rows="fixed",
        key=f"interactive_editor_{selected_row_idx}",
    )

    if not expression_valid:
        st.error(validation_message)

    col_gen, col_apply = st.columns(2)
    with col_gen:
        if st.button("Generate Sales Code", key="btn_generate_sales_code"):
            selected_by_row = get_selected_harness_pns(edited_df)
            selected_pns = selected_by_row.get(0, [])
            candidate_codes = get_candidate_codes_from_option_df(
                result["option_df"],
                circuit_name=selected_circuit,
            )

            selected_set = {pn.strip() for pn in selected_pns if str(pn).strip()}
            target_harness_keys = [
                hk for hk in result["harness_code_map"].keys()
                if hk.split("__")[0] in selected_set
            ]

            expr = ""
            if target_harness_keys and candidate_codes:
                expr = generate_sales_code_expression(
                    target_harnesses=target_harness_keys,
                    harness_code_map=result["harness_code_map"],
                    candidate_codes=candidate_codes,
                )
            else:
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
                updated_option_df = result["option_df"].copy()
                updated_option_df.loc[selected_row_idx, "Sales Code"] = generated_expr
                refreshed = run_analysis_from_option_df(temp_path, updated_option_df)
                st.session_state["analysis_result"] = refreshed
                st.success("Sales code applied. Configurations and validation refreshed.")
                st.rerun()

st.download_button(
    label="📥 Download Output Excel",
    data=result["output_excel_bytes"],
    file_name="Wiring_Harness_Output.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
