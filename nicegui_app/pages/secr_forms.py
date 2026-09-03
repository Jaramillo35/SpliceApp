"""SECR Create / Update flows + DTCR report library — NiceGUI.

Faithful ports of the Streamlit flows: batch creation from DEF-to-DEF
compares (numbers issued per Model Year + Phase scope), versioned updates of
generated SECRs, and the DTCR Matching Report library that both consume.

Each tab reads top to bottom as files → change type → preview → DTCR
report → details → generate, with the one primary gated on what it needs.
"""

from __future__ import annotations

from datetime import date

from nicegui import ui

from nicegui_app import components as c
from secrdb.core.common.errors import SpliceError
from secrdb.core.dtcr import library
from secrdb.core.secr import batch, db as secr_db, generation, identity
from secrdb.core.secr.enrich import load_dtcr_matching_report

ASSIGNMENT_LABELS = {"cnum": "CNUM", "dtcr_number": "DTCR #",
                     "harness_family": "Harness family", "changes": "Changes",
                     "source": "Source"}


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
                "Original issue date, MM/DD/YYYY",
                value=date.today().strftime("%m/%d/%Y")).classes("w-full").props("dense")
    return widgets


def read_details(widgets: dict) -> dict:
    return {key: (w.value or "") for key, w in widgets.items()}


def scope_label(model_year, program, phase) -> str:
    return f"MY{model_year or '?'} · {program or '?'} · {phase or '?'}"


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
            except Exception as exc:  # noqa: BLE001 — a missing library must not block generation
                with self._info:
                    c.note("high", f"Could not read the report library: {exc}")
        if filed:
            payload = library.report_bytes(int(filed["id"]))
            if payload:
                self.payload = payload
                with self._info:
                    c.chip("ok", f"Using {filed['filename']} from the library — "
                                 f"{scope_label(filed['model_year'], filed['program'], filed['phase'])}, "
                                 f"{filed['row_count']} DTCRs")
                    self._preview(payload)
        else:
            with self._info:
                c.note("info", "No filed report for this scope — upload one "
                               "below, or file one in the DTCR library tab and "
                               "it will be used here automatically. Without a "
                               "report the SECR is generated without enrichment.")
        c.upload_row("DTCR Matching Report override (.xlsx/.xlsm)",
                     self._on_upload, accept=".xlsx,.xlsm")

    def _on_upload(self, name: str, blob: bytes) -> None:
        self._info.clear()
        with self._info:
            try:
                self._preview(blob)
            except Exception as exc:  # noqa: BLE001 — any parse failure is reported in place
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
                 f"· {len(cnum_map)} CNUMs mapped").classes("sx-caption")


def show_result(result) -> None:
    """One generated SECR: identity, warnings, assignments, download."""
    with ui.expansion(f"{result.secr_number} V{result.version_number} — "
                      f"{result.metadata.harness_family} "
                      f"({result.change_count} changes)") \
            .classes("w-full").props("dense"):
        for warning in result.warnings or []:
            c.note("high", str(warning))
        if result.enriched and result.dtcr_assignments:
            c.frame_table([{
                "cnum": a.cnum, "dtcr_number": a.dtcr_number,
                "harness_family": a.harness_family,
                "changes": a.change_count, "source": a.source,
            } for a in result.dtcr_assignments],
                labels=ASSIGNMENT_LABELS, mono=("cnum", "dtcr_number"),
                pagination=15)
        c.download(result.filename, lambda r=result: r.secr_bytes)


# --------------------------------------------------------------------------- create

def create_tab() -> None:
    state: dict = {"files": [], "plans": [], "created": None, "signature": None,
                   "dtcr": None}

    def ready_plans() -> list:
        return [p for p in state["plans"] if p.ready]

    def missing() -> list[str]:
        if not state["files"]:
            return ["at least one DEF-to-DEF compare"]
        if not ready_plans():
            return ["a compare whose DEF metadata is complete"]
        return []

    def on_file(name: str, blob: bytes) -> None:
        state["files"].append((name, blob))
        preview.refresh()
        dtcr_input.refresh()

    with c.section("Create SECRs from DEF-to-DEF compares",
                   "Harness Family, Model Year, Phase and Program are read from "
                   "each DEF. Numbers are issued per Model Year + Phase scope, "
                   "starting at 1000, only when you press Generate."):
        c.upload_row("DEF-to-DEF compare file(s)", on_file,
                     accept=".xlsx,.xls,.xlsm", multiple=True)
        change_type = ui.radio(list(identity.CHANGE_TYPES),
                               value=list(identity.CHANGE_TYPES)[0]).props("inline")
        ui.label("Design Change issues a 'D' SECR number; Miscellaneous "
                 "issues 'M'.").classes("sx-caption")

        @ui.refreshable
        def preview() -> None:
            if not state["files"]:
                state["plans"] = []
                return
            plans = batch.plan_batch(state["files"], change_type.value)
            state["plans"] = plans
            ready = [p for p in plans if p.ready]
            ui.label("Preview").classes("sx-section")
            c.frame_table([{
                "file": p.name,
                "harness": p.metadata.harness_family or "—",
                "scope": (f"MY{p.metadata.model_year_2}/{p.metadata.phase}"
                          if p.ready else "—"),
                "number": p.number or "—",
                "status": "Ready" if p.ready else "Blocked",
            } for p in plans], mono=("file", "number"), pagination=15)
            for p in plans:
                if not p.ready:
                    c.note("blocker", f"{p.name} — {'; '.join(p.plan.problems)}")
                for warning in p.plan.warnings:
                    c.note("high", f"{p.name}: {warning}")
            if ready:
                c.note("info", f"{len(ready)} SECR(s) will be issued when you "
                               "press Generate — previewing reserves nothing.")

        preview()
        change_type.on_value_change(lambda: (preview.refresh(), dtcr_input.refresh(),
                                             c.recheck()))

    with c.section("DTCR Matching Report",
                   "The report filed for the batch's scope is used automatically; "
                   "an upload here overrides it for this generation only."):
        dtcr_holder = ui.column().classes("w-full")

        @ui.refreshable
        def dtcr_input():
            dtcr_holder.clear()
            with dtcr_holder:
                ready = ready_plans()
                state["dtcr"] = DtcrInput(ready[0].metadata if ready else None)

        dtcr_input()

    with c.section("Details for every SECR",
                   "Written into each generated workbook's header."):
        widgets = shared_details_form()

        async def generate() -> None:
            ready = ready_plans()
            guard.clear()
            if not ready:
                with guard:
                    c.note("high", "Nothing is ready to generate — every compare "
                                   "is blocked on its metadata.")
                return
            signature = batch.signature_for(state["files"], change_type.value)
            if state["created"] and state["signature"] == signature:
                with guard:
                    c.note("high", "These compares already produced SECRs — "
                                   "change the uploads first, or you would issue "
                                   "new numbers for the same work.")
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
                    c.note("blocker", f"{name} — {error}")
                if stored.results:
                    c.chip("ok", f"{len(stored.results)} SECR(s) created")
                    if len(stored.results) > 1:
                        c.download(f"SECRs_{date.today():%m%d%Y}.zip",
                                   lambda: batch.zip_results(state["created"].results))
                    for result in stored.results:
                        show_result(result)

        c.action("Generate", generate, needs=missing)
        guard = ui.column().classes("w-full gap-1")
        results_box = ui.column().classes("w-full gap-2")


# --------------------------------------------------------------------------- update

def update_tab() -> None:
    state: dict = {"def": None, "plan": None, "source": None}

    def missing() -> list[str]:
        if not state["def"]:
            return ["a new DEF-to-DEF compare"]
        if state["plan"] is None:
            return ["a compare that passes validation"]
        return []

    with c.section("Update a generated SECR",
                   "The number stays, the version advances. Imported SECRs are "
                   "not renumbered, so they are not listed."):
        try:
            candidates = secr_db.list_generated_secrs()
        except Exception as exc:  # noqa: BLE001 — the DB may be absent or locked; the tab says so
            c.note("blocker", f"Could not read the SECR database: {exc}")
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
        c.upload_row("New DEF-to-DEF compare file",
                     lambda n, b: (state.update(**{"def": (n, b)}), plan_view.refresh()),
                     accept=".xlsx,.xls,.xlsm")

    def _plan() -> object | None:
        """Validate the new DEF against the chosen SECR; every stop on the
        way says why. Returns the plan only when the update can proceed."""
        name, blob = state["def"]
        try:
            plan = generation.plan_secr_update(pick.value, blob, name)
        except SpliceError as exc:
            c.note("blocker", str(exc))
            return None
        except Exception as exc:  # noqa: BLE001 — any parse failure is reported in place
            c.note("blocker", f"Could not read the DEF compare file: {exc}")
            return None
        c.frame_table([{
            "field": d.label, "existing": d.existing or "—",
            "new": d.new or "—",
            "changed": "← changed" if d.changed else "",
        } for d in plan.differences],
            labels={"new": "New input"}, pagination=15)
        for note in plan.notes:
            c.note("info", str(note))
        if plan.problems:
            c.chip("blocker", "Metadata incomplete — the update is blocked")
            for problem in plan.problems:
                c.note("blocker", str(problem))
            return None
        for warning in plan.warnings:
            c.note("high", str(warning))
        if plan.scope_changed:
            changed = ", ".join(f"{d.label} {d.existing} → {d.new}"
                                for d in plan.changed)
            c.chip("blocker", f"SECR scope changed — {changed}")
            c.note("high", "A change of Harness Family, Model Year, Phase or "
                           "Program requires a NEW SECR — take this DEF to the "
                           "Create tab.")
            return None
        stored_src = secr_db.get_source_file(pick.value)
        if not stored_src or not stored_src.get("content"):
            c.chip("blocker", "The original workbook is not stored — re-import "
                              "or re-generate it with source storage enabled")
            return None
        state["source"] = stored_src
        c.chip("ok", f"Metadata validation passed — V{plan.current_version} "
                     f"→ V{plan.next_version}")
        ui.label(plan.filename).classes("sx-caption sx-mono")
        return plan

    @ui.refreshable
    def plan_view() -> None:
        state["plan"] = None
        plan = None
        if state["def"]:
            with c.section("Update preview",
                           "What the new DEF changes against the stored SECR."):
                plan = _plan()
        state["plan"] = plan
        dtcr = None
        if plan is not None:
            with c.section("DTCR Matching Report",
                           "The report filed for this SECR's scope is used "
                           "automatically; an upload here overrides it."):
                dtcr = DtcrInput(plan.existing_metadata)

        with c.section("Details for this version",
                       "Written into the new version's header."):
            widgets = shared_details_form()
            widgets["reissue_date"] = ui.input("Reissue date, MM/DD/YYYY") \
                .classes("w-64").props("dense")

            async def do_update() -> None:
                name, blob = state["def"]
                details = read_details(widgets)

                def work():
                    return generation.generate_secr_update(
                        blob, name, state["source"]["content"], plan,
                        subject=details["reason_for_change"],
                        secr_author=details["secr_author"],
                        design_release_engineer=details["design_release_engineer"],
                        change_requested_by=details["change_requested_by"],
                        reissue_date=details["reissue_date"],
                        phase_implemented=details["phase_implemented"],
                        pull_ahead=details["pull_ahead"],
                        dtcr_matching_bytes=dtcr.payload if dtcr else None,
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

            label = f"Generate V{plan.next_version}" if plan else "Generate next version"
            c.action(label, do_update, icon="upgrade", needs=missing)
            result_box = ui.column().classes("w-full gap-2")

    pick.on_value_change(lambda: plan_view.refresh())
    plan_view()


# --------------------------------------------------------------------------- library

def library_panel() -> None:
    with c.card("DTCR report library",
                "File one report per Program + Model Year + Phase; Create and "
                "Update use it automatically for SECRs in that scope."):
        listing = ui.column().classes("w-full gap-1")
        filed = ui.column().classes("w-full gap-1")

        def refresh() -> None:
            listing.clear()
            with listing:
                try:
                    reports = library.list_reports()
                except Exception as exc:  # noqa: BLE001 — the DB may be absent or locked; the card says so
                    c.note("blocker", f"Library unavailable: {exc}")
                    return
                if not reports:
                    c.empty("No reports filed yet.", icon="library_books")
                    return
                for r in reports:
                    with ui.row().classes("items-center gap-3 w-full"):
                        ui.label(scope_label(r["model_year"], r["program"], r["phase"])) \
                            .classes("text-sm font-semibold")
                        ui.label(f"{r['filename']} · {r['row_count']} DTCRs") \
                            .classes("sx-caption")
                        payload = library.report_bytes(int(r["id"]))
                        if payload:
                            c.download(r["filename"], lambda p=payload: p)

        def on_upload(name: str, blob: bytes) -> None:
            guess = library.parse_scope_from_filename(name)
            scope = scope_label(guess.model_year, guess.program, guess.phase)
            filed.clear()
            try:
                library.save_report(
                    blob, name,
                    program=guess.program, model_year=guess.model_year,
                    phase=guess.phase)
            except Exception as exc:  # noqa: BLE001 — any save failure is reported in place
                with filed:
                    c.note("blocker", f"Could not file {name}: {exc}")
                return
            ui.notify(f"Filed {name}", type="positive")
            with filed:
                c.note("info", f"Filed under {scope}")
            refresh()

        c.upload_row("File a DTCR Matching Report (.xlsx/.xlsm) — scope is "
                     "read from the filename", on_upload, accept=".xlsx,.xlsm")
        refresh()
