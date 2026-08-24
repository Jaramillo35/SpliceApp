"""SECR Create / Update flows + DTCR report library — NiceGUI (wave 2).

Faithful ports of the Streamlit flows: batch creation from DEF-to-DEF
compares (numbers issued per Model Year + Phase scope), versioned updates of
generated SECRs, and the DTCR Matching Report library that both consume.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme
from secrdb.core.common.errors import SpliceError
from secrdb.core.dtcr import library
from secrdb.core.secr import batch, db as secr_db, generation, identity
from secrdb.core.secr.enrich import load_dtcr_matching_report


# --------------------------------------------------------------------------- shared

def shared_details_form() -> dict:
    """The fields every SECR in a batch shares. Returns widget handles."""
    widgets = {}
    with ui.row().classes("w-full gap-6 flex-wrap"):
        with ui.column().classes("flex-1 min-w-[18rem] gap-1"):
            widgets["reason_for_change"] = ui.textarea(
                "Subject / Reason for Change").classes("w-full").props("dense")
            widgets["secr_author"] = ui.input("SECR Author").classes("w-full").props("dense")
            widgets["design_release_engineer"] = ui.input(
                "Design Release Engineer").classes("w-full").props("dense")
        with ui.column().classes("flex-1 min-w-[18rem] gap-1"):
            widgets["change_requested_by"] = ui.input(
                "Change Requested By").classes("w-full").props("dense")
            widgets["phase_implemented"] = ui.input(
                "Phase Implemented").classes("w-full").props("dense")
            widgets["pull_ahead"] = ui.select(["", "N", "Y"], value="",
                                              label="Pull Ahead").classes("w-full")
            widgets["original_issue_date"] = ui.input(
                "Original Issue Date (MM/DD/YYYY)",
                value=date.today().strftime("%m/%d/%Y")).classes("w-full").props("dense")
    return widgets


def read_details(widgets: dict) -> dict:
    return {key: (w.value or "") for key, w in widgets.items()}


def frame_table(df: pd.DataFrame, pagination: int = 15) -> None:
    if df is None or df.empty:
        ui.label("None.").classes("text-sm sx-muted")
        return
    view = df.astype(str)
    ui.table(rows=view.to_dict("records"), columns=[
        {"name": col, "label": col, "field": col, "align": "left"}
        for col in view.columns], pagination=pagination) \
        .classes("w-full").props("dense flat")


class DtcrInput:
    """Library-first DTCR Matching Report input with upload override."""

    def __init__(self, scope=None):
        self.payload: bytes | None = None
        self._info = ui.column().classes("w-full gap-1")
        filed = None
        if scope is not None:
            try:
                filed = library.find_report_for_scope(
                    scope.program, scope.model_year, scope.phase)
            except Exception as exc:
                ui.label(f"Could not read the report library: {exc}") \
                    .classes("text-xs sx-muted")
        if filed:
            payload = library.report_bytes(int(filed["id"]))
            if payload:
                self.payload = payload
                with self._info:
                    c.chip("ok", f"Using {filed['filename']} from the library — "
                                 f"MY{filed['model_year']} · {filed['program']} · "
                                 f"{filed['phase']}, {filed['row_count']} DTCRs")
                    self._preview(payload)
        else:
            ui.label("No filed report for this scope — upload one below, or "
                     "file one in the Dashboard tab and it will be used here "
                     "automatically. Without a report the SECR is generated "
                     "without enrichment.").classes("text-xs sx-muted")
        c.upload_zone("DTCR Matching Report override (.xlsx/.xlsm)",
                      self._on_upload, accept=".xlsx,.xlsm")

    def _on_upload(self, name: str, blob: bytes) -> None:
        self._info.clear()
        with self._info:
            try:
                self._preview(blob)
            except Exception as exc:
                c.chip("blocker", f"Could not read the report: {exc}")
                return
            c.chip("info", f"Using uploaded {name} for this generation only")
        self.payload = blob

    def _preview(self, payload: bytes) -> None:
        mapping_df = load_dtcr_matching_report(payload)
        usable = mapping_df[mapping_df["Status"].astype(str).str.strip()
                            .isin(["Complete", "Draft"])]
        cnum_map = generation.build_cnum_dtcr_map(usable)
        ui.label(f"{len(mapping_df)} DTCR rows · {len(usable)} Complete/Draft "
                 f"· {len(cnum_map)} CNUMs mapped").classes("text-xs sx-muted")


def show_result(result) -> None:
    """One generated SECR: identity, warnings, assignments, download."""
    with ui.expansion(f"{result.secr_number} V{result.version_number} — "
                      f"{result.metadata.harness_family} "
                      f"({result.change_count} changes)") \
            .classes("w-full").props("dense"):
        for warning in result.warnings or []:
            ui.label(f"• {warning}").classes("text-xs") \
                .style(f"color:{theme.STATUS['high']}")
        if result.enriched and result.dtcr_assignments:
            frame_table(pd.DataFrame([{
                "CNUM": a.cnum, "DTCR #": a.dtcr_number,
                "Harness Family": a.harness_family,
                "Changes": a.change_count, "Source": a.source,
            } for a in result.dtcr_assignments]))
        c.download_button(result.filename, lambda r=result: r.secr_bytes)


# --------------------------------------------------------------------------- create

def create_tab() -> None:
    state: dict = {"files": [], "created": None, "signature": None}

    with c.card("Create SECRs from DEF-to-DEF compares",
                "Harness Family, Model Year, Phase and Program are read from "
                "each DEF. Numbers are issued per Model Year + Phase scope, "
                "starting at 1000, only when you press Generate."):
        c.upload_zone("DEF-to-DEF compare file(s)",
                      lambda n, b: (state["files"].append((n, b)),
                                    preview.refresh(), dtcr_input.refresh()),
                      accept=".xlsx,.xls,.xlsm", multiple=True)
        change_type = ui.radio(list(identity.CHANGE_TYPES), value=list(identity.CHANGE_TYPES)[0]) \
            .props("inline")
        ui.label("Design Change issues a 'D' SECR number; Miscellaneous "
                 "issues 'M'.").classes("text-xs sx-muted")

        @ui.refreshable
        def preview() -> None:
            if not state["files"]:
                return
            plans = batch.plan_batch(state["files"], change_type.value)
            ready = [p for p in plans if p.ready]
            frame_table(pd.DataFrame([{
                "File": p.name,
                "Harness": p.metadata.harness_family or "—",
                "Scope": (f"MY{p.metadata.model_year_2}/{p.metadata.phase}"
                          if p.ready else "—"),
                "Number": p.number or "—",
                "Status": "Ready" if p.ready else "Blocked",
            } for p in plans]))
            for p in plans:
                if not p.ready:
                    ui.label(f"{p.name} — {'; '.join(p.plan.problems)}") \
                        .classes("text-xs").style(f"color:{theme.STATUS['blocker']}")
                for warning in p.plan.warnings:
                    ui.label(f"{p.name}: {warning}").classes("text-xs") \
                        .style(f"color:{theme.STATUS['high']}")
            if ready:
                ui.label(f"{len(ready)} SECR(s) will be issued when you press "
                         "Generate — previewing reserves nothing.") \
                    .classes("text-xs sx-muted")

        preview()
        change_type.on_value_change(lambda: preview.refresh())

        ui.separator()
        ui.label("DTCR Matching Report").classes("text-sm font-bold")
        dtcr_holder = ui.column().classes("w-full")

        @ui.refreshable
        def dtcr_input():
            dtcr_holder.clear()
            with dtcr_holder:
                plans = batch.plan_batch(state["files"], change_type.value) \
                    if state["files"] else []
                ready = [p for p in plans if p.ready]
                state["dtcr"] = DtcrInput(ready[0].metadata if ready else None)

        dtcr_input()

        ui.separator()
        ui.label("Details for every SECR").classes("text-sm font-bold")
        widgets = shared_details_form()
        results_box = ui.column().classes("w-full gap-2")

        async def generate() -> None:
            plans = batch.plan_batch(state["files"], change_type.value)
            ready = [p for p in plans if p.ready]
            if not ready:
                ui.notify("Nothing is ready to generate", type="warning")
                return
            signature = batch.signature_for(state["files"], change_type.value)
            if state["created"] and state["signature"] == signature:
                ui.notify("These compares already produced SECRs — change the "
                          "uploads first, or you would issue new numbers for "
                          "the same work.", type="warning")
                return
            shared = read_details(widgets)
            mapping = getattr(state.get("dtcr"), "payload", None)

            def work():
                return batch.generate_batch(ready, shared, mapping)

            stored = await c.run_engine(
                work, running=f"Generating {len(ready)} SECR(s)…",
                done="SECRs generated")
            if stored is None:
                return
            state["created"], state["signature"] = stored, signature
            results_box.clear()
            with results_box:
                for name, error in stored.failures:
                    ui.label(f"{name} — {error}") \
                        .style(f"color:{theme.STATUS['blocker']}")
                if stored.results:
                    c.chip("ok", f"{len(stored.results)} SECR(s) created")
                    if len(stored.results) > 1:
                        c.download_button(
                            f"SECRs_{date.today():%m%d%Y}.zip",
                            lambda: batch.zip_results(state["created"].results))
                    for result in stored.results:
                        show_result(result)

        ui.button("Generate", icon="play_arrow", on_click=generate) \
            .props("unelevated")


# --------------------------------------------------------------------------- update

def update_tab() -> None:
    state: dict = {"def": None, "plan": None, "record_id": None}

    with c.card("Update a generated SECR",
                "The number stays, the version advances. Imported SECRs are "
                "not renumbered, so they are not listed."):
        try:
            candidates = secr_db.list_generated_secrs()
        except Exception as exc:
            ui.label(f"Could not read the SECR database: {exc}") \
                .style(f"color:{theme.STATUS['blocker']}")
            return
        if not candidates:
            c.empty("No generated SECRs yet — create one in the Create tab first.")
            return
        options = {r["id"]: f"MY{r['scope_model_year']} / {r['scope_phase']} / "
                            f"{r['secr_sequence_number']} · {r['secr_number']} "
                            f"(current V{r['version_number']})"
                   for r in candidates}
        pick = ui.select(options, value=next(iter(options)),
                         label="SECR to update").classes("w-full")
        c.upload_zone("New DEF-to-DEF compare file",
                      lambda n, b: (state.update(**{"def": (n, b)}), plan_view.refresh()),
                      accept=".xlsx,.xls,.xlsm")

        @ui.refreshable
        def plan_view() -> None:
            if not state["def"]:
                return
            name, blob = state["def"]
            try:
                plan = generation.plan_secr_update(pick.value, blob, name)
            except SpliceError as exc:
                ui.label(str(exc)).style(f"color:{theme.STATUS['blocker']}")
                return
            except Exception as exc:
                ui.label(f"Could not read the DEF compare file: {exc}") \
                    .style(f"color:{theme.STATUS['blocker']}")
                return
            state["plan"] = plan
            frame_table(pd.DataFrame([{
                "Field": d.label, "Existing": d.existing or "—",
                "New Input": d.new or "—",
                "": "← changed" if d.changed else "",
            } for d in plan.differences]))
            for note in plan.notes:
                ui.label(f"ℹ {note}").classes("text-xs sx-muted")
            if plan.problems:
                c.chip("blocker", "Metadata incomplete — the update is blocked")
                for problem in plan.problems:
                    ui.label(f"• {problem}") \
                        .style(f"color:{theme.STATUS['blocker']}")
                return
            for warning in plan.warnings:
                ui.label(warning).classes("text-xs") \
                    .style(f"color:{theme.STATUS['high']}")
            if plan.scope_changed:
                changed = ", ".join(f"{d.label} {d.existing} → {d.new}"
                                    for d in plan.changed)
                c.chip("blocker", f"SECR scope changed — {changed}")
                ui.label("A change of Harness Family, Model Year, Phase or "
                         "Program requires a NEW SECR — take this DEF to the "
                         "Create tab.").classes("text-sm") \
                    .style(f"color:{theme.STATUS['high']}")
                return
            stored_src = secr_db.get_source_file(pick.value)
            if not stored_src or not stored_src.get("content"):
                c.chip("blocker", "The original workbook is not stored — "
                                  "re-import or re-generate it with source "
                                  "storage enabled")
                return
            c.chip("ok", f"Metadata validation passed — V{plan.current_version} "
                         f"→ V{plan.next_version}")
            ui.label(plan.filename).classes("text-xs sx-mono")

            ui.label("DTCR Matching Report").classes("text-sm font-bold mt-2")
            dtcr = DtcrInput(plan.existing_metadata)
            ui.label("Details for this version").classes("text-sm font-bold mt-2")
            widgets = shared_details_form()
            widgets["reissue_date"] = ui.input("ReIssue Date (MM/DD/YYYY)") \
                .classes("w-64").props("dense")
            result_box = ui.column().classes("w-full gap-2")

            async def do_update() -> None:
                details = read_details(widgets)

                def work():
                    return generation.generate_secr_update(
                        blob, name, stored_src["content"], plan,
                        subject=details["reason_for_change"],
                        secr_author=details["secr_author"],
                        design_release_engineer=details["design_release_engineer"],
                        change_requested_by=details["change_requested_by"],
                        reissue_date=details["reissue_date"],
                        phase_implemented=details["phase_implemented"],
                        pull_ahead=details["pull_ahead"],
                        dtcr_matching_bytes=dtcr.payload,
                    )

                result = await c.run_engine(
                    work, running=f"Generating V{plan.next_version}…",
                    done="New version created")
                if result is None:
                    return
                result_box.clear()
                with result_box:
                    c.chip("ok", f"{result.secr_number} V{result.version_number} — "
                                 f"{result.change_count} change record(s) stored")
                    show_result(result)

            ui.button(f"Generate V{plan.next_version}", icon="upgrade",
                      on_click=do_update).props("unelevated")

        pick.on_value_change(lambda: plan_view.refresh())
        plan_view()


# --------------------------------------------------------------------------- library

def library_panel() -> None:
    with c.card("DTCR report library",
                "File one report per Program + Model Year + Phase; Create and "
                "Update use it automatically for SECRs in that scope."):
        listing = ui.column().classes("w-full gap-1")

        def refresh() -> None:
            listing.clear()
            with listing:
                try:
                    reports = library.list_reports()
                except Exception as exc:
                    ui.label(f"Library unavailable: {exc}") \
                        .style(f"color:{theme.STATUS['blocker']}")
                    return
                if not reports:
                    c.empty("No reports filed yet.", icon="library_books")
                    return
                for r in reports:
                    with ui.row().classes("items-center gap-3 w-full"):
                        ui.label(f"MY{r['model_year']} · {r['program']} · "
                                 f"{r['phase']}").classes("text-sm font-semibold")
                        ui.label(f"{r['filename']} · {r['row_count']} DTCRs") \
                            .classes("text-xs sx-muted")
                        payload = library.report_bytes(int(r["id"]))
                        if payload:
                            c.download_button(r["filename"],
                                              lambda p=payload: p)

        def on_upload(name: str, blob: bytes) -> None:
            guess = library.parse_scope_from_filename(name)
            try:
                library.save_report(
                    blob, name,
                    program=guess.program, model_year=guess.model_year,
                    phase=guess.phase)
                ui.notify(f"Filed {name} for MY{guess.model_year} · "
                          f"{guess.program} · {guess.phase}", type="positive")
            except Exception as exc:
                ui.notify(f"Could not file the report: {exc}", type="negative")
            refresh()

        c.upload_zone("File a DTCR Matching Report (.xlsx/.xlsm) — scope is "
                      "read from the filename", on_upload, accept=".xlsx,.xlsm")
        refresh()
