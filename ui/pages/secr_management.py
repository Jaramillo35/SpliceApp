"""SECR Management — one guided page covering the whole SECR workflow.

The flow runs left to right:

    1. DTCR Matching   -> map DTCR records to harness families
    2. Create SECR     -> build a SECR workbook from a DEF
    3. Enrich          -> fill Reason-for-Change / DTCR / bulletin cells
    4. Update SECR     -> revise an existing SECR against a new DEF
    5. Database        -> save, search, and trace SECR revisions

Every step is thin UI: it validates its inputs, calls a ``splice`` engine, shows
an actionable error instead of a stack trace, and stashes its output under a
``secrmgmt_*`` session key so later steps can pick it up automatically. Steps can
also be run on their own.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from splice.dtcr import match_dtcr_to_harness_family
from splice.secr import db as secr_db
from splice.secr.enrich import (
    export_dtcr_mapping_styled,
    load_dtcr_report,
    load_dtx_circuits_report,
)
from splice.secr.generate import create_secr_bytes, update_secr_bytes
from splice.secr.numbering import (
    auto_enrich_secr,
    build_secr_number_preview,
    extract_secr_number_inputs_from_def,
)

# Session-state namespace so this page can't collide with other tools' keys.
NS = "secrmgmt_"


def _k(name: str) -> str:
    return f"{NS}{name}"


def render() -> None:
    """Render the full SECR Management page."""
    st.title("SECR Management")
    st.caption(
        "From DTCR report matching all the way to an updated SECR — one guided flow."
    )

    with st.expander("How this page works", expanded=False):
        st.markdown(
            """
            Work through the tabs in order, or jump to the step you need:

            1. **DTCR Matching** — upload the DTCR report and the DTx circuits
               report to map each DTCR to its harness family. Download the
               *DTCR Matching Report* workbook (used in step 3).
            2. **Create SECR** — upload the DEF-to-DEF compare file and fill in
               the SECR details. The SECR number is previewed before you build.
            3. **Enrich** — apply a DTCR Matching Report to a created SECR to
               auto-fill Reason for Change, DTCR numbers, and bulletin numbers.
            4. **Update SECR** — revise an existing SECR against a new DEF.
            5. **Database** — every created/updated SECR is saved here; search
               by DTCR or item and trace a SECR's revision history.

            Outputs carry forward automatically (a SECR created in step 2 is
            offered to steps 3 and 5), and nothing here changes the workbook
            formats your downstream tools consume.
            """
        )

    tab_match, tab_create, tab_enrich, tab_update, tab_db = st.tabs(
        [
            "1 · DTCR Matching",
            "2 · Create SECR",
            "3 · Enrich",
            "4 · Update SECR",
            "5 · Database",
        ]
    )
    with tab_match:
        _step_dtcr_matching()
    with tab_create:
        _step_create_secr()
    with tab_enrich:
        _step_enrich()
    with tab_update:
        _step_update_secr()
    with tab_db:
        _step_database()


# ---------------------------------------------------------------------------
# Step 1 — DTCR Matching
# ---------------------------------------------------------------------------
def _step_dtcr_matching() -> None:
    st.subheader("Step 1 · DTCR Report Matching")
    st.markdown(
        "Map each DTCR record to a harness family. Upload the **DTCR report** "
        "(Excel or the extension's `DTCR_Summary.csv`) and the **DTx circuits "
        "report**. The result is the *DTCR Matching Report* used to enrich a SECR."
    )

    col_dtcr, col_dtx = st.columns(2)
    with col_dtcr:
        dtcr_file = st.file_uploader(
            "DTCR report", type=["xlsx", "xlsm", "xls", "csv"], key=_k("match_dtcr_file")
        )
    with col_dtx:
        dtx_file = st.file_uploader(
            "DTx circuits report", type=["xlsx", "xlsm", "xls"], key=_k("match_dtx_file")
        )

    if dtcr_file is None or dtx_file is None:
        st.info("Upload both files to generate the DTCR Matching Report.")
        return

    if st.button("Generate DTCR Matching Report", type="primary", key=_k("match_run")):
        try:
            with st.spinner("Matching DTCRs to harness families..."):
                dtcr_df = load_dtcr_report(dtcr_file.getvalue(), dtcr_file.name)
                dtx_df = load_dtx_circuits_report(dtx_file.getvalue())
                mapping_df = match_dtcr_to_harness_family(dtcr_df, dtx_df)
                mapping_bytes = export_dtcr_mapping_styled(mapping_df)
        except ValueError as exc:
            st.error(f"Could not build the matching report: {exc}")
            return
        except Exception as exc:  # noqa: BLE001 - surface unexpected errors cleanly
            st.error(f"Unexpected error while matching DTCRs: {exc}")
            return

        st.session_state[_k("mapping_df")] = mapping_df
        st.session_state[_k("mapping_bytes")] = mapping_bytes
        st.success(f"Matched {len(mapping_df)} DTCR record(s).")

    mapping_df = st.session_state.get(_k("mapping_df"))
    mapping_bytes = st.session_state.get(_k("mapping_bytes"))
    if mapping_df is not None:
        matched = (mapping_df["Match Method"] != "No Match").sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("DTCR records", len(mapping_df))
        c2.metric("Matched", int(matched))
        c3.metric("No match", int((mapping_df["Match Method"] == "No Match").sum()))
        st.dataframe(mapping_df, use_container_width=True, hide_index=True)
        if mapping_bytes is not None:
            st.download_button(
                "Download DTCR Matching Report (.xlsx)",
                data=mapping_bytes,
                file_name="DTCR_Matching_Report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=_k("match_download"),
            )
            st.caption("This workbook is picked up automatically in step 3 (Enrich).")


# ---------------------------------------------------------------------------
# Step 2 — Create SECR
# ---------------------------------------------------------------------------
def _step_create_secr() -> None:
    st.subheader("Step 2 · Create SECR")
    st.markdown(
        "Build a SECR workbook from a **DEF-to-DEF compare file**. Model Year, "
        "Program, and Phase are pre-filled from the DEF when possible."
    )

    def_file = st.file_uploader(
        "DEF-to-DEF compare file",
        type=["xlsx", "xls", "xlsm"],
        key=_k("create_def_file"),
        help="Filename pattern e.g. 2027_RU_X2_A_vs_2026_RU_X2_A_IP_DEF_DEF_Compare_...xlsx",
    )
    if def_file is None:
        st.info("Upload the DEF-to-DEF compare file to continue.")
        return

    extracted_my, extracted_program, extracted_phase = extract_secr_number_inputs_from_def(
        def_file.getvalue()
    )
    stem_parts = def_file.name.rsplit(".", 1)[0].split("_")
    default_my = extracted_my or (stem_parts[0] if stem_parts else "")
    default_program = extracted_program or (stem_parts[1] if len(stem_parts) > 1 else "")
    default_phase = extracted_phase or (
        f"{stem_parts[2]}{stem_parts[3]}".replace("_", "") if len(stem_parts) > 3 else ""
    )

    with st.form(_k("create_form")):
        st.markdown("**SECR number**")
        n1, n2, n3, n4 = st.columns(4)
        model_year = n1.text_input("MY", value=default_my, key=_k("create_my"))
        program = n2.text_input("Program", value=default_program, key=_k("create_program"))
        phase = n3.text_input("Phase", value=default_phase, key=_k("create_phase"))
        change_type = n4.selectbox(
            "SECR # Type", ["Miscellaneous", "Design Change"], key=_k("create_change_type")
        )
        st.text_input(
            "SECR # preview",
            value=build_secr_number_preview(model_year, program, phase, change_type),
            disabled=True,
            key=_k("create_preview"),
            help="{D|M} + last 2 of MY + PROGRAM + PHASE + _1000",
        )

        st.markdown("**Details**")
        left, right = st.columns(2)
        with left:
            subject = st.text_area("Subject / Reason for Change", height=100, key=_k("create_subject"))
            author = st.text_input("SECR Author", key=_k("create_author"))
            dre = st.text_input("Design Release Engineer", key=_k("create_dre"))
            crb = st.text_input("Change Requested By", key=_k("create_crb"))
        with right:
            version = st.text_input("Version", value="A", key=_k("create_version"))
            phase_impl = st.text_input("Phase Implemented", key=_k("create_phase_impl"))
            pull_ahead = st.selectbox("Pull Ahead", ["", "N", "Y"], key=_k("create_pull_ahead"))
            orig_date = st.text_input("Original Issue Date (MM/DD/YYYY)", key=_k("create_orig_date"))
            reissue_date = st.text_input("ReIssue Date (blank if N/A)", key=_k("create_reissue_date"))

        submitted = st.form_submit_button("Generate SECR", type="primary")

    if not submitted:
        _offer_created_secr_download()
        return

    try:
        with st.spinner("Building SECR workbook..."):
            secr_bytes, meta = create_secr_bytes(
                def_bytes=def_file.getvalue(),
                def_filename=def_file.name,
                reason_for_change=subject,
                secr_author=author,
                design_release_engineer=dre,
                change_requested_by=crb,
                original_issue_date=orig_date,
                reissue_date=reissue_date,
                version=version,
                phase_implemented=phase_impl,
                pull_ahead=pull_ahead,
                secr_change_type=change_type,
                secr_model_year=model_year,
                secr_program=program,
                secr_phase=phase,
            )
    except ValueError as exc:
        st.error(f"Could not create the SECR: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        st.error(f"Unexpected error while creating the SECR: {exc}")
        return

    st.session_state[_k("secr_bytes")] = secr_bytes
    st.session_state[_k("secr_filename")] = meta.get("filename", "SECR_output.xlsx")
    st.session_state[_k("secr_enriched")] = False
    st.session_state[_k("secr_change_type")] = change_type
    st.session_state[_k("secr_source_def")] = def_file.name

    # Persist to the database (never blocks generation).
    _save_secr_to_db(secr_bytes, action="create", source_def=def_file.name,
                     filename=meta.get("filename", ""), change_type=change_type)

    st.success(f"SECR created: {meta.get('filename', '')}")
    _offer_created_secr_download()


def _offer_created_secr_download() -> None:
    secr_bytes = st.session_state.get(_k("secr_bytes"))
    if not secr_bytes:
        return
    st.download_button(
        "Download SECR (.xlsx)",
        data=secr_bytes,
        file_name=st.session_state.get(_k("secr_filename"), "SECR_output.xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=_k("create_download"),
    )
    st.caption("Available in step 3 (Enrich) without re-uploading.")


# ---------------------------------------------------------------------------
# Step 3 — Enrich
# ---------------------------------------------------------------------------
def _step_enrich() -> None:
    st.subheader("Step 3 · Enrich SECR")
    st.markdown(
        "Apply a **DTCR Matching Report** to a SECR to auto-fill Reason for "
        "Change, DTCR numbers, and bulletin numbers. Only *Complete* / *Draft* "
        "DTCR rows are used."
    )

    has_created = bool(st.session_state.get(_k("secr_bytes")))
    use_created = False
    if has_created:
        use_created = st.checkbox(
            f"Use the SECR created in step 2 "
            f"({st.session_state.get(_k('secr_filename'))})",
            value=True,
            key=_k("enrich_use_created"),
        )
    secr_upload = None
    if not use_created:
        secr_upload = st.file_uploader(
            "SECR workbook", type=["xlsx", "xlsm"], key=_k("enrich_secr_file")
        )

    has_mapping = bool(st.session_state.get(_k("mapping_bytes")))
    use_mapping = False
    if has_mapping:
        use_mapping = st.checkbox(
            "Use the DTCR Matching Report from step 1", value=True, key=_k("enrich_use_mapping")
        )
    mapping_upload = None
    if not use_mapping:
        mapping_upload = st.file_uploader(
            "DTCR Matching Report workbook", type=["xlsx", "xlsm"], key=_k("enrich_mapping_file")
        )

    secr_bytes = st.session_state.get(_k("secr_bytes")) if use_created else (
        secr_upload.getvalue() if secr_upload else None
    )
    mapping_bytes = st.session_state.get(_k("mapping_bytes")) if use_mapping else (
        mapping_upload.getvalue() if mapping_upload else None
    )

    if not secr_bytes or not mapping_bytes:
        st.info("Provide a SECR workbook and a DTCR Matching Report to enrich.")
        return

    if st.button("Enrich SECR", type="primary", key=_k("enrich_run")):
        try:
            with st.spinner("Enriching SECR..."):
                filename = st.session_state.get(_k("secr_filename"), "SECR_output.xlsx")
                enriched_bytes, meta, mapping_df, summary_df, family = auto_enrich_secr(
                    secr_bytes, mapping_bytes, filename
                )
        except ValueError as exc:
            st.error(f"Could not enrich the SECR: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            st.error(f"Unexpected error while enriching: {exc}")
            return

        st.session_state[_k("enriched_bytes")] = enriched_bytes
        st.session_state[_k("enriched_filename")] = meta.get("filename", filename)
        st.session_state[_k("enriched_summary")] = summary_df
        st.success(f"Enriched using harness family: {family}")
        st.dataframe(summary_df, use_container_width=True, hide_index=True)

    enriched_bytes = st.session_state.get(_k("enriched_bytes"))
    if enriched_bytes:
        st.download_button(
            "Download enriched SECR (.xlsx)",
            data=enriched_bytes,
            file_name=st.session_state.get(_k("enriched_filename"), "SECR_enriched.xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=_k("enrich_download"),
        )


# ---------------------------------------------------------------------------
# Step 4 — Update SECR
# ---------------------------------------------------------------------------
def _step_update_secr() -> None:
    st.subheader("Step 4 · Update SECR")
    st.markdown(
        "Revise an existing SECR against a **new DEF**. Prior comments are "
        "merged and the revision / reissue row is advanced."
    )

    col_def, col_secr = st.columns(2)
    with col_def:
        def_file = st.file_uploader(
            "New DEF-to-DEF compare file", type=["xlsx", "xls", "xlsm"], key=_k("update_def_file")
        )
    with col_secr:
        old_secr_file = st.file_uploader(
            "Existing SECR workbook", type=["xlsx", "xlsm"], key=_k("update_old_secr_file")
        )

    if def_file is None or old_secr_file is None:
        st.info("Upload the new DEF and the existing SECR to continue.")
        return

    extracted_my, extracted_program, extracted_phase = extract_secr_number_inputs_from_def(
        def_file.getvalue()
    )
    with st.form(_k("update_form")):
        n1, n2, n3, n4 = st.columns(4)
        model_year = n1.text_input("MY", value=extracted_my, key=_k("update_my"))
        program = n2.text_input("Program", value=extracted_program, key=_k("update_program"))
        phase = n3.text_input("Phase", value=extracted_phase, key=_k("update_phase"))
        change_type = n4.selectbox(
            "SECR # Type", ["Miscellaneous", "Design Change"], key=_k("update_change_type")
        )
        left, right = st.columns(2)
        with left:
            subject = st.text_area("Subject / Reason for Change", height=100, key=_k("update_subject"))
            author = st.text_input("SECR Author", key=_k("update_author"))
            dre = st.text_input("Design Release Engineer", key=_k("update_dre"))
            crb = st.text_input("Change Requested By", key=_k("update_crb"))
        with right:
            version = st.text_input("Version", value="B", key=_k("update_version"))
            phase_impl = st.text_input("Phase Implemented", key=_k("update_phase_impl"))
            pull_ahead = st.selectbox("Pull Ahead", ["", "N", "Y"], key=_k("update_pull_ahead"))
            reissue_date = st.text_input("ReIssue Date (MM/DD/YYYY)", key=_k("update_reissue_date"))
        submitted = st.form_submit_button("Generate Updated SECR", type="primary")

    if not submitted:
        _offer_updated_secr_download()
        return

    try:
        with st.spinner("Building updated SECR..."):
            update_bytes, meta = update_secr_bytes(
                def_bytes=def_file.getvalue(),
                def_filename=def_file.name,
                old_secr_bytes=old_secr_file.getvalue(),
                subject=subject,
                secr_author=author,
                design_release_engineer=dre,
                change_requested_by=crb,
                reissue_date=reissue_date,
                version=version,
                phase_implemented=phase_impl,
                pull_ahead=pull_ahead,
                secr_change_type=change_type,
                secr_model_year=model_year,
                secr_program=program,
                secr_phase=phase,
            )
    except ValueError as exc:
        st.error(f"Could not update the SECR: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        st.error(f"Unexpected error while updating the SECR: {exc}")
        return

    st.session_state[_k("update_bytes")] = update_bytes
    st.session_state[_k("update_filename")] = meta.get("filename", "SECR_updated.xlsx")
    parent_number = None
    try:
        parent_number = secr_db.read_secr_number(old_secr_file.getvalue())
    except Exception:
        parent_number = None
    _save_secr_to_db(update_bytes, action="update", source_def=def_file.name,
                     filename=meta.get("filename", ""), change_type=change_type,
                     parent_secr_number=parent_number)
    st.success(f"Updated SECR created: {meta.get('filename', '')}")
    _offer_updated_secr_download()


def _offer_updated_secr_download() -> None:
    update_bytes = st.session_state.get(_k("update_bytes"))
    if not update_bytes:
        return
    st.download_button(
        "Download updated SECR (.xlsx)",
        data=update_bytes,
        file_name=st.session_state.get(_k("update_filename"), "SECR_updated.xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=_k("update_download"),
    )


# ---------------------------------------------------------------------------
# Step 5 — Database
# ---------------------------------------------------------------------------
def _step_database() -> None:
    st.subheader("Step 5 · SECR Database")
    st.markdown("Every SECR created or updated on this page is recorded here.")

    try:
        secr_db.init_db()
        records = secr_db.list_secrs()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not open the SECR database: {exc}")
        return

    if not records:
        st.info("No SECRs recorded yet. Create one in step 2 to populate the database.")
        return

    st.metric("Recorded SECRs", len(records))
    search = st.text_input("Search by DTCR # or item", key=_k("db_search"))
    shown = records
    if search.strip():
        term = search.strip()
        try:
            hit_ids = {r["id"] for r in secr_db.find_by_dtcr(term)}
            hit_ids |= {r["id"] for r in secr_db.find_by_item(term)}
            shown = [r for r in records if r["id"] in hit_ids]
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Search failed: {exc}")

    st.dataframe(pd.DataFrame(shown), use_container_width=True, hide_index=True)

    if shown:
        label_to_id = {
            f"{r.get('secr_number') or r.get('filename') or r['id']} (#{r['id']})": r["id"]
            for r in shown
        }
        picked = st.selectbox("Inspect a SECR's revision history", list(label_to_id), key=_k("db_pick"))
        if picked:
            try:
                chain = secr_db.get_revision_chain(label_to_id[picked])
                st.write("Revision chain (oldest first):")
                st.dataframe(pd.DataFrame(chain), use_container_width=True, hide_index=True)
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Could not load revision chain: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _save_secr_to_db(
    secr_bytes: bytes,
    *,
    action: str,
    source_def: str,
    filename: str,
    change_type: str,
    parent_secr_number: str | None = None,
) -> None:
    """Persist a SECR record; surface a warning but never block on failure."""
    try:
        record = secr_db.record_from_workbook(
            secr_bytes,
            action=action,
            source_def_filename=source_def,
            filename=filename,
            change_type=change_type,
            parent_secr_number=parent_secr_number,
        )
        secr_db.save_secr(record)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"SECR was generated, but saving to the database failed: {exc}")
