from __future__ import annotations

import queue
import tempfile
import threading
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from dtcr_engine import start_dtcr_session, zip_download_dir
from dtx_compare_engine import generate_dtx_change_report
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
            Select a workflow below to launch either wiring splice generation or DTx report comparison.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

mode = st.radio(
    "Choose Tool",
    ["Home", "Splice Generation", "DTx Compare Report", "DTCR Downloader"],
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
                <div class="tool-title">DTCR Downloader</div>
                <div class="tool-desc">
                    Automate DTCR attachment downloads from Chrysler iSPEED. Extracts Reason for Change data and exports an Excel report.
                </div>
                <span class="tool-badge">Local Only</span>
                <span class="tool-badge">Playwright</span>
                <span class="tool-badge">Attachments</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open DTCR Downloader", key="go_dtcr", use_container_width=True):
            st.session_state["selected_tool"] = "DTCR Downloader"
            st.rerun()

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
                    refreshed = run_analysis_from_option_df(temp_path, updated_option_df)
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

elif selected_tool == "DTCR Downloader":
    st.title("DTCR Downloader")
    st.warning(
        "This tool opens a real Chromium browser window. "
        "It must be run **locally** — it will not function on Streamlit Cloud."
    )
    st.markdown(
        """
        **Workflow:**
        1. Enter your iSPEED credentials below and click **Launch DTCR Browser**.
        2. A Chromium window will open. The tool will attempt to log you in automatically.
        3. Navigate to the **Change Requests** tab, enter **Program** and **Phase**, then click **Search**.
        4. When results load, click the orange **Download DTCRs** button in the browser overlay panel.
        5. The scraper downloads all DTCR attachments and extracts Reason for Change data.
        6. Return here to download a ZIP of all files and the Reason-for-Change Excel report.
        """
    )

    # Initialise session-state keys on first visit.
    _dtcr_defaults = {
        "dtcr_running": False,
        "dtcr_completed": False,
        "dtcr_logs": [],
        "dtcr_done_event": None,
        "dtcr_log_queue": None,
        "dtcr_result_holder": {},
        "dtcr_download_dir": "",
    }
    for _k, _v in _dtcr_defaults.items():
        if _k not in st.session_state:
            st.session_state[_k] = _v

    # ── Launch form (shown when idle and no completed session) ─────────────
    if not st.session_state["dtcr_running"] and not st.session_state["dtcr_completed"]:
        with st.form("dtcr_launch_form"):
            username_val = st.text_input(
                "iSPEED Username (optional — speeds up login)",
                key="dtcr_uname",
            )
            password_val = st.text_input(
                "iSPEED Password (optional)",
                type="password",
                key="dtcr_pwd",
            )
            launched = st.form_submit_button("Launch DTCR Browser", type="primary")

        if launched:
            dl_dir = tempfile.mkdtemp(prefix="dtcr_downloads_")
            lq: queue.Queue = queue.Queue()
            ev = threading.Event()
            rh: dict = {}
            st.session_state["dtcr_running"] = True
            st.session_state["dtcr_log_queue"] = lq
            st.session_state["dtcr_done_event"] = ev
            st.session_state["dtcr_result_holder"] = rh
            st.session_state["dtcr_download_dir"] = dl_dir
            st.session_state["dtcr_logs"] = []
            start_dtcr_session(username_val, password_val, dl_dir, lq, ev, rh)
            st.rerun()

    # ── Polling loop while the background thread is running ────────────────
    if st.session_state["dtcr_running"]:
        lq = st.session_state["dtcr_log_queue"]
        ev = st.session_state["dtcr_done_event"]

        # Drain any new log messages into session state.
        if lq is not None:
            while not lq.empty():
                try:
                    st.session_state["dtcr_logs"].append(lq.get_nowait())
                except Exception:
                    break

        logs_text = "\n".join(st.session_state["dtcr_logs"])
        if logs_text:
            st.text_area("Session Log", value=logs_text, height=260, key="dtcr_log_running")

        if ev is not None and ev.is_set():
            # Thread finished — transition to completed state.
            st.session_state["dtcr_running"] = False
            st.session_state["dtcr_completed"] = True
            st.rerun()
        else:
            st.info("Browser session running — complete the steps in the Chromium window...")
            time.sleep(1.5)
            st.rerun()

    # ── Results panel shown after session completes ────────────────────────
    if st.session_state["dtcr_completed"]:
        logs_text = "\n".join(st.session_state.get("dtcr_logs", []))
        if logs_text:
            st.text_area("Session Log", value=logs_text, height=260, key="dtcr_log_done")

        rh = st.session_state.get("dtcr_result_holder", {})
        dl_dir = st.session_state.get("dtcr_download_dir", "")

        if rh.get("results"):
            res = rh["results"]
            st.success(
                f"Download complete — {res.get('processed', 0)} DTCRs processed, "
                f"{res.get('failed', 0)} failed."
            )
            if dl_dir:
                zip_bytes = zip_download_dir(dl_dir)
                st.download_button(
                    label="Download All Files (ZIP)",
                    data=zip_bytes,
                    file_name="dtcr_downloads.zip",
                    mime="application/zip",
                    key="dtcr_zip_dl",
                )
        elif rh.get("error"):
            st.error(f"Session failed: {rh['error']}")
        else:
            st.warning("Session ended with no results.")

        st.markdown("---")
        if st.button("Start New Session", key="dtcr_new_session"):
            for _k in list(_dtcr_defaults.keys()):
                if _k in st.session_state:
                    del st.session_state[_k]
            st.rerun()
