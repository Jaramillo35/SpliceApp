"""HRN Chart Builder: batch-convert HRN + Matrix CSV (+ CMP) into chart workbooks.

Upload any mix of .hrn / .csv / .cmp files; they pair into jobs by matching
file name (case/punctuation-insensitive), one job per HRN. Each workbook is
named {HarnessFamily}_{ModelYear}{Program}_Chart_{MMDDYYYY} with the family,
year, and program extracted from the HRN file name and the date of the run.

The page is thin: all logic lives in :mod:`splice.hrncmp.engine`, which the
splice-api container exposes as ``POST /hrn/chart`` for the Docker/Kubernetes
deployment.
"""

from __future__ import annotations

import io
import json
import re
import zipfile

import pandas as pd
import streamlit as st

from splice.hrncmp import engine, supplier_tickets


def _norm_stem(name: str) -> str:
    stem = name.rsplit('.', 1)[0]
    return re.sub(r'[^a-z0-9]', '', stem.lower())


def _pair_jobs(uploads):
    """Group uploads into per-HRN jobs by normalized stem."""
    hrns, csvs, cmps = {}, {}, {}
    for f in uploads:
        suffix = f.name.rsplit('.', 1)[-1].lower()
        bucket = {'hrn': hrns, 'csv': csvs, 'cmp': cmps}.get(suffix)
        if bucket is not None:
            bucket[_norm_stem(f.name)] = f
    jobs = []
    for ns, hrn in sorted(hrns.items()):
        jobs.append({
            'hrn': hrn,
            'csv': csvs.get(ns),
            'cmp': cmps.get(ns),
        })
    # a single shared csv/cmp is allowed when there is exactly one of them
    if len(csvs) == 1 and any(j['csv'] is None for j in jobs):
        only_csv = next(iter(csvs.values()))
        for j in jobs:
            j['csv'] = j['csv'] or only_csv
    if len(cmps) == 1 and any(j['cmp'] is None for j in jobs):
        only_cmp = next(iter(cmps.values()))
        for j in jobs:
            j['cmp'] = j['cmp'] or only_cmp
    return jobs


def _handle_supplier_ticket(supplier_upload) -> None:
    """File (or reuse) a supplier-update ticket and hand it to the user."""
    uploaded_map = engine.load_supplier_map(supplier_upload.getvalue())
    if not uploaded_map:
        return  # unreadable file — the build step reports this to the user
    shipped = engine.default_supplier_map()
    try:
        from feedback_system import FeedbackStore
        store = FeedbackStore()
        ticket_id, diff, already = supplier_tickets.file_supplier_ticket(
            supplier_upload.name, uploaded_map, shipped, store=store)
    except Exception as e:
        st.warning(f"Supplier ticket could not be filed: {e}")
        return
    if ticket_id is None:
        st.info("Uploaded list matches the shipped one — no update ticket needed.")
        return

    n_add, n_rem, n_chg = len(diff['added']), len(diff['removed']), len(diff['changed'])
    if already:
        st.info(f"Update ticket **{ticket_id}** is already open for this exact "
                f"list ({n_add} added, {n_rem} removed, {n_chg} changed).")
    else:
        st.success(f"Update ticket **{ticket_id}** filed "
                   f"({n_add} added, {n_rem} removed, {n_chg} changed). Your "
                   "conversions below already use the uploaded list.")

    ticket = next((t for t in store.load_tickets()
                   if t.get("ticket_id") == ticket_id), None)
    if ticket is not None:
        st.download_button(
            f"⬇ Download ticket {ticket_id}",
            data=json.dumps(ticket, indent=2).encode(),
            file_name=f"{ticket_id}.json",
            mime="application/json",
            key=f"user_tkt_{ticket_id}",
        )
        st.markdown(
            "**To get the shipped list updated for everyone:**\n"
            f"1. Download ticket `{ticket_id}` with the button above.\n"
            "2. Send the file to the app administrator (Martín) by email or "
            "Teams.\n\n"
            "Until the update ships, keep uploading your modified list here — "
            "your conversions always use it."
        )


def _render_admin_tickets() -> None:
    tickets = supplier_tickets.list_supplier_tickets()
    if not tickets:
        return
    open_tickets = [t for t in tickets if t.get("status") != "applied"]
    label = (f"Supplier update tickets — {len(open_tickets)} open "
             f"({len(tickets)} total) · admin")
    with st.expander(label):
        st.caption(
            "Administrator: download a ticket and hand its JSON to Claude "
            "(\"apply supplier ticket ...\") — it regenerates the shipped "
            "`DEF Supplier Codes.xlsx` from the ticket's `full_list` and marks "
            "the ticket applied."
        )
        for t in sorted(tickets, key=lambda x: x.get("created_at", ""), reverse=True):
            col_info, col_dl = st.columns([3, 1])
            status = t.get("status", "new")
            badge = "🟢 applied" if status == "applied" else f"🟠 {status}"
            col_info.markdown(
                f"**{t.get('ticket_id')}** · {badge} · "
                f"{t.get('created_at', '')[:16]} · {t.get('reported_by', '')}"
            )
            col_dl.download_button(
                "Download JSON",
                data=json.dumps(t, indent=2).encode(),
                file_name=f"{t.get('ticket_id', 'ticket')}.json",
                mime="application/json",
                key=f"tkt_{t.get('ticket_id')}",
            )


def render() -> None:
    st.title("HRN Chart Builder")
    st.caption(
        "Combine `.hrn` circuit files with their harness matrix `.csv` (and "
        "optional `.cmp` connector map) into styled chart workbooks. Output "
        "naming: `{HarnessFamily}_{ModelYear}{Program}_Chart_{MMDDYYYY}`, "
        "dated the day of the run."
    )

    uploads = st.file_uploader(
        "Upload HRN / CSV / CMP files (any mix — they pair by file name)",
        type=['hrn', 'csv', 'cmp'],
        accept_multiple_files=True,
    )

    supplier_upload = None
    with st.expander("Supplier list"):
        st.caption(
            "Used to tag CNUMs with supplier prefixes (`PN-111~DZ`). The "
            "shipped `DEF Supplier Codes.xlsx` is used by default."
        )
        if engine.DEFAULT_SUPPLIER_PATH.exists():
            st.download_button(
                "⬇ Download DEF Supplier Codes.xlsx",
                data=engine.DEFAULT_SUPPLIER_PATH.read_bytes(),
                file_name=engine.DEFAULT_SUPPLIER_PATH.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        st.markdown(
            "**Missing or outdated supplier?** Download the list above, edit "
            "it, and upload it below — your HRN generations will use it right "
            "away. Uploading a modified list also **files a ticket** for the "
            "administrator so the shipped list gets updated for everyone."
        )
        supplier_upload = st.file_uploader(
            "Override supplier list (Excel/CSV)", type=['xlsx', 'xls', 'csv'])
        if supplier_upload is not None:
            _handle_supplier_ticket(supplier_upload)

    _render_admin_tickets()

    if not uploads:
        st.info("Add files to build the batch.", icon="📄")
        return

    jobs = _pair_jobs(uploads)
    if not jobs:
        st.warning("No `.hrn` files in the upload — nothing to convert.")
        return

    preview = pd.DataFrame([{
        'HRN file': j['hrn'].name,
        'Harness': engine.parse_hrn_filename(
            j['hrn'].name.rsplit('.', 1)[0]).family or '?',
        'Matrix CSV': j['csv'].name if j['csv'] else '— missing —',
        'CMP': j['cmp'].name if j['cmp'] else '—',
        'Output': f"{engine.output_basename(j['hrn'].name)}.xlsx",
    } for j in jobs])
    st.dataframe(preview, width="stretch", hide_index=True)

    runnable = [j for j in jobs if j['csv'] is not None]
    skipped = len(jobs) - len(runnable)
    if skipped:
        st.warning(f"{skipped} HRN file(s) have no matching CSV and will be skipped.")

    if not runnable or not st.button(
            f"Build {len(runnable)} chart(s)", type="primary"):
        return

    supplier_map = None
    if supplier_upload is not None:
        supplier_map = engine.load_supplier_map(supplier_upload.getvalue())
        if not supplier_map:
            st.error("Could not read a name/prefix mapping from the supplier file.")
            return

    results, errors = [], []
    used_names: set = set()
    progress = st.progress(0.0)
    for i, job in enumerate(runnable):
        try:
            res = engine.build_chart(
                job['hrn'].name,
                job['hrn'].getvalue(),
                job['csv'].getvalue(),
                job['cmp'].getvalue() if job['cmp'] else None,
                supplier_map=supplier_map,
            )
            # two HRNs can resolve to the same chart name in one batch
            name, n = res.filename, 1
            while name in used_names:
                n += 1
                name = res.filename.replace('.xlsx', f'_{n}.xlsx')
            used_names.add(name)
            res.filename = name
            results.append(res)
        except Exception as e:
            errors.append((job['hrn'].name, str(e)))
        progress.progress((i + 1) / len(runnable))

    for hrn_name, err in errors:
        st.error(f"{hrn_name}: {err}")

    if not results:
        return

    st.success(f"{len(results)} workbook(s) built.")
    for res in results:
        col_dl, col_diag = st.columns([1, 2])
        col_dl.download_button(
            res.filename, data=res.workbook, file_name=res.filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"dl_{res.filename}",
        )
        notes = []
        if res.unmatched:
            notes.append(f"{len(res.unmatched)} unmatched connector(s)")
        if res.invalid_prefixes:
            notes.append(f"{len(res.invalid_prefixes)} invalid supplier prefix(es)")
        if notes:
            with col_diag.expander(", ".join(notes)):
                if res.unmatched:
                    st.dataframe(pd.DataFrame(res.unmatched), hide_index=True)
                if res.invalid_prefixes:
                    st.dataframe(pd.DataFrame(res.invalid_prefixes), hide_index=True)

    if len(results) > 1:
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for res in results:
                zf.writestr(res.filename, res.workbook)
        st.download_button(
            "Download all as ZIP", data=zbuf.getvalue(),
            file_name="hrn_charts.zip", mime="application/zip",
        )


render()
