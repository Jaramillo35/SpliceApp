from __future__ import annotations

import io
import inspect
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from dtx_compare_engine import generate_dtx_change_report
from secr_engine import create_secr_bytes
from secr_enrichment_engine import (
    load_dtcr_report,
    load_dtx_circuits_report,
    load_generated_secr_workbook,
    match_dtcr_to_harness_family,
    get_secr_harness_family_from_c12,
    find_reason_for_change_cell,
    find_dtcr_number_label_cell,
    update_secr_reason_for_change,
    update_secr_dtcr_numbers,
    build_reason_for_change_for_secr,
    build_dtcr_numbers_for_secr,
    build_enrichment_summary,
    validate_enrichment_inputs,
    export_dtcr_mapping_styled,
    export_secr_enriched_output,
)
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


st.set_page_config(page_title="Wiring System Engineer Tools", layout="wide")

LOGO_PATH = Path(__file__).resolve().parent / "assets" / "versigent_logo_horizontal.jpg"
if LOGO_PATH.exists():
    st.image(str(LOGO_PATH), width=300)

st.markdown(
    """
    <style>
        .hero {
            padding: 1.25rem 1.5rem;
            border-radius: 16px;
            border: 1px solid #d9e4ee;
            background: linear-gradient(135deg, #f3f8fc 0%, #eef6f2 100%);
            margin-bottom: 1.2rem;
        }
        .tool-card {
            border: 1px solid #d6e1ea;
            border-radius: 14px;
            padding: 1rem;
            background: #ffffff;
            min-height: 220px;
            box-shadow: 0 8px 16px rgba(26, 43, 60, 0.05);
        }
        .tool-title {
            font-size: 1.2rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            color: #14324a;
        }
        .tool-desc {
            color: #35526b;
            margin-bottom: 1rem;
        }
        .tool-badge {
            display: inline-block;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            font-size: 0.8rem;
            font-weight: 600;
            background: #e8f4ff;
            color: #0b5ea8;
            margin-right: 0.35rem;
            margin-bottom: 0.45rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
        <h1 style="margin-bottom: 0.35rem; color: #10273a;">Wiring System Engineer Tools</h1>
        <p style="margin: 0; color: #2f4b62;">
            Select a workflow below to launch wiring splice generation, DTx report comparison, or SECR creation.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

mode = st.radio(
    "Choose Tool",
    ["Home", "Splice Generation", "DTx Compare Report", "Create SECR"],
    horizontal=True,
    label_visibility="collapsed",
)

if mode == "Home":
    left, mid, right = st.columns(3, gap="large")

    with left:
        st.markdown(
            """
            <div class="tool-card">
                <div class="tool-title">Splice Generation</div>
                <div class="tool-desc">
                    Build harness configurations, generated connections, print matrix, and interactive sales code validation.
                </div>
                <span class="tool-badge">Complexity</span>
                <span class="tool-badge">OptionPerCkt</span>
                <span class="tool-badge">Output Excel</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open Splice Generation", key="go_splice", use_container_width=True):
            st.session_state["selected_tool"] = "Splice Generation"
            st.rerun()

    with mid:
        st.markdown(
            """
            <div class="tool-card">
                <div class="tool-title">DTx Compare Report</div>
                <div class="tool-desc">
                    Compare OLD vs NEW DTx reports, review added/removed/modified CNUM and circuits, and download a dashboard workbook.
                </div>
                <span class="tool-badge">OLD vs NEW</span>
                <span class="tool-badge">Change Log</span>
                <span class="tool-badge">Dashboard</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open DTx Compare", key="go_dtx", use_container_width=True):
            st.session_state["selected_tool"] = "DTx Compare Report"
            st.rerun()

    with right:
        st.markdown(
            """
            <div class="tool-card">
                <div class="tool-title">Create SECR</div>
                <div class="tool-desc">
                    Generate a SECR workbook from a DEF-to-DEF compare file. Auto-fills connector, circuit, and DEF summary changes into the SECR template.
                </div>
                <span class="tool-badge">DEF Compare</span>
                <span class="tool-badge">SECR Template</span>
                <span class="tool-badge">Output Excel</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open Create SECR", key="go_secr", use_container_width=True):
            st.session_state["selected_tool"] = "Create SECR"
            st.rerun()

    st.markdown("---")
    st.subheader("Windows App Downloads")

    st.markdown(
        """
        <div class="tool-card">
            <div class="tool-title">VBOM Risk Matrix (Windows)</div>
            <div class="tool-desc">
                Download the full Windows package with executable, install steps, and all runtime files.
            </div>
            <span class="tool-badge">Windows Package</span>
            <span class="tool-badge">Install Guide Included</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    project_root = Path(__file__).resolve().parent
    vbom_pkg = project_root / "assets" / "downloads" / "VBOM_Generator.exe"
    if vbom_pkg.exists():
        st.download_button(
            label="Download VBOM Windows Executable",
            data=vbom_pkg.read_bytes(),
            file_name="VBOM_Generator.exe",
            mime="application/octet-stream",
            key="dl_vbom_windows_pkg",
            use_container_width=True,
        )
    else:
        st.warning("VBOM package not found. Expected: assets/downloads/VBOM_Generator.exe")

if mode != "Home":
    st.session_state["selected_tool"] = mode

selected_tool = st.session_state.get("selected_tool", "Home")

if selected_tool == "Splice Generation":
    st.title("Wiring Harness Splice Generator")
    st.caption("Generate harness print-ready direct connections, splices, configuration groups, and validation reports.")

    uploaded_file = st.file_uploader("Upload Excel file (Complexity + OptionPerCkt)", type=["xlsx", "xls"])

    if uploaded_file is None:
        st.info("Upload Input.xlsx (or equivalent) to begin analysis.")
        st.stop()

    # CAN Mode Configuration
    st.markdown("---")
    st.subheader("Splice Configuration Options")
    can_mode = st.checkbox("Apply CAN splice rules: maximum 3 ends per splice", value=False)
    if can_mode:
        st.info("CAN mode enabled: Each splice will be limited to a maximum of 3 endpoints. Additional splices and splice-to-splice connections will be created as needed for configurations with more than 3 endpoints.")
    
    st.session_state["can_mode"] = can_mode

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as temp_file:
        temp_file.write(uploaded_file.getbuffer())
        temp_path = temp_file.name

    try:
        run_analysis_sig = inspect.signature(run_analysis)
        if "can_mode" in run_analysis_sig.parameters:
            result = run_analysis(temp_path, can_mode=can_mode)
        else:
            result = run_analysis(temp_path)
            if can_mode:
                st.warning("CAN mode is not available in the loaded backend yet. Please reboot/redeploy the app.")
    except Exception as exc:
        st.error(f"Analysis failed: {exc}")
        st.stop()

    if "analysis_result" not in st.session_state:
        st.session_state["analysis_result"] = result
    else:
        prev_name = st.session_state.get("uploaded_file_name")
        if prev_name != uploaded_file.name:
            st.session_state["analysis_result"] = result

    st.session_state["uploaded_file_name"] = uploaded_file.name
    result = st.session_state["analysis_result"]

    st.subheader("Input Previews")
    left, right = st.columns(2)
    with left:
        st.markdown("**Complexity Matrix (normalized)**")
        st.dataframe(result["harness_code_map_df"], use_container_width=True)
    with right:
        st.markdown("**OptionPerCircuit (normalized)**")
        st.dataframe(result["option_df"], use_container_width=True)

    st.subheader("Generated Configurations")
    st.dataframe(result["configurations_df"], use_container_width=True)

    # Display CAN validation results if CAN mode is enabled
    if result.get("can_mode", False):
        st.markdown("---")
        if result.get("can_validation_passed", True):
            st.success(f"✓ {result.get('can_validation_message', 'CAN validation passed')}")
        else:
            st.error(f"✗ {result.get('can_validation_message', 'CAN validation failed')}")

    st.subheader("Generated Connections")
    conns_df = result["generated_connections_df"]
    configs_df = result["configurations_df"]

    config_lookup = {}
    for _, cfg in configs_df.iterrows():
        key = (cfg["Circuit Name"], cfg["Configuration ID"])
        config_lookup[key] = {
            "topology_type": cfg["Topology Type"],
            "target_harness_pns": cfg["Target Harness PNs"],
        }

    for (circuit, config_id), group in conns_df.groupby(["Circuit Name", "Configuration"], sort=False):
        cfg_details = config_lookup.get((circuit, config_id), {})
        topology = cfg_details.get("topology_type", "Unknown")
        target_pns = cfg_details.get("target_harness_pns", "")

        if config_id == conns_df[conns_df["Circuit Name"] == circuit]["Configuration"].iloc[0]:
            st.markdown(f"### Circuit {circuit}")

        st.markdown(f"**Configuration {config_id} | {topology}**")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"**Connections:** {len(group)}")
        with col2:
            st.markdown(f"**Topology:** {topology}")
        with col3:
            st.markdown(f"**Target PNs:** {target_pns}")

        st.dataframe(group, use_container_width=True)
        st.markdown("---")

    st.subheader("Harness Print Matrix")
    st.markdown("Engineering applicability matrix showing which connections apply to each Harness PN:")
    st.dataframe(result["harness_print_matrix_df"], use_container_width=True)

    st.subheader("Interactive Sales Code Generator")
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
                    can_mode_for_refresh = st.session_state.get("can_mode", False)
                    refresh_sig = inspect.signature(run_analysis_from_option_df)
                    if "can_mode" in refresh_sig.parameters:
                        refreshed = run_analysis_from_option_df(
                            temp_path,
                            updated_option_df,
                            can_mode=can_mode_for_refresh,
                        )
                    else:
                        refreshed = run_analysis_from_option_df(temp_path, updated_option_df)
                        if can_mode_for_refresh:
                            st.warning("CAN mode is not available in the loaded backend yet. Please reboot/redeploy the app.")
                    st.session_state["analysis_result"] = refreshed
                    st.success("Sales code applied. Configurations and validation refreshed.")
                    st.rerun()

    st.download_button(
        label="Download Output Excel",
        data=result["output_excel_bytes"],
        file_name="Wiring_Harness_Output.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

elif selected_tool == "DTx Compare Report":
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
                dtx_result = generate_dtx_change_report(
                    old_file_bytes=old_file.getvalue(),
                    new_file_bytes=new_file.getvalue(),
                    old_file_name=old_file.name,
                    new_file_name=new_file.name,
                )
            st.session_state["dtx_compare_result"] = dtx_result
        except Exception as exc:
            st.error(f"DTx comparison failed: {exc}")

    dtx_result = st.session_state.get("dtx_compare_result")
    if dtx_result is None:
        st.stop()

    st.success("Comparison complete.")

    metric_cols = st.columns(5)
    metric_cols[0].metric("Added CNUMs", int(dtx_result["added_cnum_count"]))
    metric_cols[1].metric("Removed CNUMs", int(dtx_result["removed_cnum_count"]))
    metric_cols[2].metric("Added Circuits", int(dtx_result["added_circuit_count"]))
    metric_cols[3].metric("Removed Circuits", int(dtx_result["removed_circuit_count"]))
    metric_cols[4].metric("Modified Circuits", int(dtx_result["modified_circuit_count"]))

    st.subheader("Detected Layout")
    layout_left, layout_right = st.columns(2)
    old_layout = dtx_result["old_layout"]
    new_layout = dtx_result["new_layout"]
    layout_left.info(f"OLD: sheet '{old_layout.sheet_name}', header row {old_layout.header_row + 1}")
    layout_right.info(f"NEW: sheet '{new_layout.sheet_name}', header row {new_layout.header_row + 1}")

    st.subheader("Preview Tables")
    with st.expander("Added Circuits", expanded=False):
        st.dataframe(dtx_result["added_circuits_df"], use_container_width=True)
    with st.expander("Removed Circuits", expanded=False):
        st.dataframe(dtx_result["removed_circuits_df"], use_container_width=True)
    with st.expander("Modified Circuits", expanded=True):
        st.dataframe(dtx_result["modified_circuits_df"], use_container_width=True)
    with st.expander("CNUM Summary", expanded=False):
        st.dataframe(dtx_result["cnum_summary_df"], use_container_width=True)
    with st.expander("Field Change Frequency", expanded=False):
        st.dataframe(dtx_result["field_change_frequency_df"], use_container_width=True)

    st.download_button(
        label="Download DTx Compare Workbook",
        data=dtx_result["output_excel_bytes"],
        file_name=dtx_result["output_file_name"],
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

elif selected_tool == "Create SECR":
    st.title("Create SECR")
    st.caption(
        "Upload a DEF-to-DEF compare Excel file, fill in the SECR details, "
        "and download a completed SECR workbook."
    )

    def_file = st.file_uploader(
        "DEF-to-DEF Compare file",
        type=["xlsx", "xls", "xlsm"],
        key="secr_def_file",
    )

    if def_file is None:
        st.info(
            "Upload the DEF-to-DEF compare file to continue.  \n"
            "Expected filename pattern: `2027_RU_X2_A_vs_2026_RU_X2_A_IP_DEF_DEF_Compare_...xlsx`"
        )
        st.stop()

    with st.form("secr_details_form"):
        st.subheader("SECR Details")

        col_a, col_b = st.columns(2)
        with col_a:
            reason_for_change = st.text_area(
                "Reason for Change", height=100, key="secr_reason"
            )
            secr_author = st.text_input("SECR Author", key="secr_author")
            design_release_engineer = st.text_input(
                "Design Release Engineer", key="secr_dre"
            )
            change_requested_by = st.text_input(
                "Change Requested By", key="secr_crb"
            )
        with col_b:
            version = st.text_input("Version", value="A", key="secr_version")
            phase_implemented = st.text_input(
                "Phase Implemented", key="secr_phase_impl"
            )
            pull_ahead = st.selectbox(
                "Pull Ahead (Y/N)", options=["", "N", "Y"], key="secr_pull_ahead"
            )
            original_issue_date = st.text_input(
                "Original Issue Date (MM/DD/YYYY)", key="secr_orig_date"
            )
            reissue_date = st.text_input(
                "ReIssue Date (MM/DD/YYYY — leave blank if N/A)",
                key="secr_reissue_date",
            )
            m_code_suffix = st.number_input(
                "SECR Number (3-digit suffix, e.g. 1 → M27001)",
                min_value=1,
                max_value=999,
                value=1,
                step=1,
                key="secr_m_suffix",
            )

        generate_clicked = st.form_submit_button("Generate SECR", type="primary")

    if generate_clicked:
        try:
            with st.spinner("Building SECR workbook..."):
                secr_bytes, meta = create_secr_bytes(
                    def_bytes=def_file.getvalue(),
                    def_filename=def_file.name,
                    reason_for_change=reason_for_change,
                    secr_author=secr_author,
                    design_release_engineer=design_release_engineer,
                    change_requested_by=change_requested_by,
                    original_issue_date=original_issue_date,
                    reissue_date=reissue_date,
                    version=version,
                    phase_implemented=phase_implemented,
                    pull_ahead=pull_ahead,
                    m_code_suffix=int(m_code_suffix),
                )
            st.session_state["secr_result_bytes"] = secr_bytes
            st.session_state["secr_result_filename"] = meta["filename"]
            st.session_state["secr_result_meta"] = meta
        except Exception as exc:
            st.error(f"SECR creation failed: {exc}")

    secr_result = st.session_state.get("secr_result_bytes")
    if secr_result is not None:
        meta = st.session_state.get("secr_result_meta", {})
        st.success("SECR workbook created successfully.")
        col1, col2, col3 = st.columns(3)
        col1.metric("M Code", meta.get("I2", ""))
        col2.metric("Vehicle Line", meta.get("C11", ""))
        col3.metric("Phase", meta.get("F10", ""))
        st.download_button(
            label="Download SECR Excel",
            data=secr_result,
            file_name=st.session_state.get("secr_result_filename", "SECR_output.xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="secr_dl_btn",
        )

        # ──────────────────────────────────────────────────────────────────
        # Optional: SECR Reason for Change Enrichment
        # ──────────────────────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("SECR Optional Enrichment")
        st.markdown(
            "Optionally enrich the SECR Reason for Change field with DTCR data. "
            "Upload DTCR Report and DTx Circuits Report files to proceed."
        )

        enrich_col1, enrich_col2 = st.columns(2)
        with enrich_col1:
            dtcr_file = st.file_uploader(
                "DTCR Report (Excel)",
                type=["xlsx", "xls", "xlsm"],
                key="enrich_dtcr_file",
            )
        with enrich_col2:
            dtx_file = st.file_uploader(
                "DTx Circuits Report (Excel)",
                type=["xlsx", "xls", "xlsm"],
                key="enrich_dtx_file",
            )

        if dtcr_file is not None and dtx_file is not None:
            # --- Download DTCR-Harness Family mapping table immediately after upload ---
            try:
                _dtcr_prev = load_dtcr_report(dtcr_file.getvalue())
                _dtx_prev = load_dtx_circuits_report(dtx_file.getvalue())
                _mapping_prev = match_dtcr_to_harness_family(_dtcr_prev, _dtx_prev)
                _map_bytes = export_dtcr_mapping_styled(_mapping_prev)
                st.download_button(
                    label="Download DTCR → Harness Family Table",
                    data=_map_bytes,
                    file_name="DTCR_Harness_Family_Mapping.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_dtcr_mapping_quick",
                )
            except Exception as _map_err:
                st.warning(f"Could not generate DTCR mapping table: {_map_err}")

            with st.form("secr_enrichment_form"):
                st.markdown("**Enrichment Settings**")
                enable_enrichment = st.checkbox(
                    "Enable SECR Reason for Change Enrichment",
                    value=True,
                    key="enrich_enable",
                )
                status_options = ["Complete", "Draft", "Rejected", "Deleted"]
                status_filter = st.multiselect(
                    "Filter DTCRs by Status",
                    options=status_options,
                    default=["Complete", "Draft"],
                    key="enrich_status_filter",
                )
                enrich_clicked = st.form_submit_button(
                    "Run SECR Enrichment", type="primary"
                )

            if enrich_clicked and enable_enrichment:
                try:
                    with st.spinner("Processing SECR enrichment..."):
                        # Load files
                        dtcr_df = load_dtcr_report(dtcr_file.getvalue())
                        dtx_df = load_dtx_circuits_report(dtx_file.getvalue())
                        secr_wb = load_generated_secr_workbook(secr_result)

                        # Apply status filter
                        if status_filter:
                            dtcr_df = dtcr_df[dtcr_df["Status"].astype(str).str.strip().isin(status_filter)]

                        # Validate inputs
                        is_valid, validation_warnings = validate_enrichment_inputs(
                            dtcr_df,
                            dtx_df,
                            get_secr_harness_family_from_c12(secr_wb),
                        )
                        if not is_valid:
                            for warning in validation_warnings:
                                st.warning(warning)
                            st.error("Enrichment cannot proceed with validation errors.")
                            st.stop()

                        # Extract and match
                        dtcr_mapping_df = match_dtcr_to_harness_family(dtcr_df, dtx_df)
                        secr_harness_family = get_secr_harness_family_from_c12(secr_wb)

                        # Build enrichment summary
                        reason_text = build_reason_for_change_for_secr(
                            secr_harness_family, dtcr_mapping_df
                        )
                        summary_df = build_enrichment_summary(
                            dtcr_mapping_df, secr_harness_family, reason_text
                        )

                        # Update SECR
                        reason_cell_info = find_reason_for_change_cell(secr_wb)
                        if reason_cell_info:
                            _, cell_ref = reason_cell_info
                            update_secr_reason_for_change(
                                secr_wb, cell_ref, reason_text
                            )
                        else:
                            st.warning(
                                "Could not find Reason for Change field in SECR. "
                                "Skipping update."
                            )

                        # Populate DTCR # field (cell right of DTCR # label)
                        dtcr_label_info = find_dtcr_number_label_cell(secr_wb)
                        if dtcr_label_info:
                            _, dtcr_label_ref = dtcr_label_info
                            dtcr_numbers_text = build_dtcr_numbers_for_secr(
                                secr_harness_family, dtcr_mapping_df
                            )
                            update_secr_dtcr_numbers(
                                secr_wb, dtcr_label_ref, dtcr_numbers_text
                            )
                        else:
                            st.warning(
                                "Could not find DTCR # field in SECR. "
                                "Skipping DTCR # update."
                            )

                        # Export enriched output
                        base_secr_filename = st.session_state.get(
                            "secr_result_filename", "SECR_output.xlsx"
                        )
                        enriched_bytes, export_meta = export_secr_enriched_output(
                            secr_wb,
                            dtcr_df,
                            dtcr_mapping_df,
                            summary_df,
                            output_filename=base_secr_filename,
                        )

                        # Store in session
                        st.session_state["enriched_secr_bytes"] = enriched_bytes
                        st.session_state["enriched_secr_filename"] = (
                            export_meta["filename"]
                        )

                except ValueError as ve:
                    st.error(f"Validation error: {ve}")
                except Exception as exc:
                    st.error(f"Enrichment failed: {exc}")

            # Show preview if enrichment has been run
            enriched_result = st.session_state.get("enriched_secr_bytes")
            if enriched_result is not None:
                st.success("SECR enrichment complete.")

                # Prominent download buttons
                dl_col1, dl_col2 = st.columns(2)
                with dl_col1:
                    st.download_button(
                        label="Download Updated SECR with DTCRs",
                        data=enriched_result,
                        file_name=st.session_state.get(
                            "enriched_secr_filename", "SECR_Enriched.xlsx"
                        ),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="enrich_dl_secr_top",
                        use_container_width=True,
                    )
                with dl_col2:
                    try:
                        _dtcr_dl = load_dtcr_report(dtcr_file.getvalue())
                        _dtx_dl = load_dtx_circuits_report(dtx_file.getvalue())
                        if status_filter:
                            _dtcr_dl = _dtcr_dl[_dtcr_dl["Status"].astype(str).str.strip().isin(status_filter)]
                        _map_dl = match_dtcr_to_harness_family(_dtcr_dl, _dtx_dl)
                        _map_dl_bytes = export_dtcr_mapping_styled(_map_dl)
                        st.download_button(
                            label="Download DTCR → Harness Family Table",
                            data=_map_dl_bytes,
                            file_name="DTCR_Harness_Family_Mapping.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="dl_dtcr_mapping_post",
                            use_container_width=True,
                        )
                    except Exception:
                        pass

                # Show preview tables
                try:
                    dtcr_df = load_dtcr_report(dtcr_file.getvalue())
                    dtx_df = load_dtx_circuits_report(dtx_file.getvalue())
                    secr_wb = load_generated_secr_workbook(secr_result)

                    # Apply status filter
                    if status_filter:
                        dtcr_df = dtcr_df[
                            dtcr_df["Status"].astype(str).str.strip().isin(status_filter)
                        ]

                    dtcr_mapping_df = match_dtcr_to_harness_family(dtcr_df, dtx_df)
                    secr_harness_family = get_secr_harness_family_from_c12(secr_wb)
                    reason_text = build_reason_for_change_for_secr(
                        secr_harness_family, dtcr_mapping_df
                    )
                    summary_df = build_enrichment_summary(
                        dtcr_mapping_df, secr_harness_family, reason_text
                    )

                    with st.expander("Preview: Extracted DTCR Data"):
                        st.dataframe(dtcr_df, use_container_width=True)

                    with st.expander("Preview: DTCR-to-Harness Family Mapping"):
                        st.dataframe(dtcr_mapping_df, use_container_width=True)

                    with st.expander("Preview: Enrichment Summary"):
                        st.dataframe(summary_df, use_container_width=True)

                    with st.expander("Preview: Matching DTCRs for This SECR"):
                        matching_for_secr = dtcr_mapping_df[
                            dtcr_mapping_df["Harness Family"] == secr_harness_family
                        ]
                        if matching_for_secr.empty:
                            st.info("No DTCRs match the SECR Harness Family.")
                        else:
                            st.dataframe(
                                matching_for_secr[
                                    ["DTCR#", "Device Transmittal", "Reason for change", "Harness Family"]
                                ],
                                use_container_width=True,
                            )


                except Exception as exc:
                    st.error(f"Failed to display preview: {exc}")
