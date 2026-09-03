"""VBOM Risk Matrix — NiceGUI workbench over splice.vbom.run_vbom_workflow.

Archetype B (workbench). Four steps in page order — Inputs, Generate,
Review gate, DEFE — named in a sticky step bar from the first paint; a KPI
strip under it follows the same state; the header says who saved the review
last. Every review-gate decision is written through
:mod:`splice.vbom.review_store` under the engineer's name, and a regenerated
bundle arrives with those decisions restored (study finding F7 for VBOM).
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme

STEPS = ("Inputs", "Generate", "Review gate", "DEFE")
BUNDLE_NAME = "VBOM_Risk_Matrix_Bundle.zip"


class _Upload:
    """Adapter with the .name/.getbuffer() surface the workflow expects."""

    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getbuffer(self):
        return self._data

    def getvalue(self) -> bytes:
        return self._data

    def read(self) -> bytes:
        return self._data


def _guide() -> None:
    """How the tool works and what each output file is for."""
    from splice.vbom.guide import GUIDE_MD
    with ui.expansion("How the VBOM works, and what each output file is for "
                      "— read me first", icon="school") \
            .classes("w-full").props("dense"):
        ui.markdown(GUIDE_MD).classes("text-sm")


@ui.page("/vbom")
def page() -> None:
    from splice.vbom import review as review_engine
    from splice.vbom import review_store as store

    stored = store.load()
    state: dict = {
        "input": None, "complexity": [],
        "zip": None, "files": {}, "result": None,
        #: ReviewID -> chosen PN / reviewer note / who decided it and when
        "resolutions": {}, "notes": {}, "decided": {},
        "defe": None,
        #: the store as we last saw it, and its envelope
        "stored": stored,
        "revision": stored.get("revision", 0),
        "saved_by": stored.get("saved_by", ""),
        "saved_at": stored.get("saved", ""),
    }
    views: dict = {}

    # ------------------------------------------------------------ facts
    def my_value() -> str:
        return (my.value or "").strip()

    def program_value() -> str:
        return (program.value or "").strip()

    def review_total() -> int:
        r = state["result"]
        return 0 if r is None else len(r["review_df"])

    def unresolved() -> int:
        return review_total() - len(state["resolutions"])

    def gate_clear() -> bool:
        return state["result"] is not None and unresolved() == 0

    def missing_inputs() -> list[str]:
        out = []
        if not my_value():
            out.append("model year")
        if not program_value():
            out.append("program")
        if not state["input"]:
            out.append("the DoAll / BuildSpec file")
        if not state["complexity"]:
            out.append("at least one complexity file")
        return out

    def missing_for_defe() -> list[str]:
        if state["result"] is None:
            return ["a generated bundle"]
        n = unresolved()
        return [f"{n} unresolved case(s)"] if n else []

    # ------------------------------------------------------------ sync
    def show_envelope() -> None:
        if not state["saved_at"]:
            envelope.set_text("Nothing saved yet")
        else:
            by = state["saved_by"] or "unknown"
            envelope.set_text(
                f"Saved by {by} · {state['saved_at'][:16]} · rev {state['revision']}")

    def sync() -> None:
        """Step states and KPIs follow the state; nothing sets them by hand."""
        inputs_ready = not missing_inputs()
        r = state["result"]
        if r is None:
            states = {
                "Inputs": (("done", f"{len(state['complexity'])} complexity file(s)")
                           if inputs_ready else ("current", "")),
                "Generate": (("current", "") if inputs_ready else ("waiting", "")),
                "Review gate": ("waiting", ""),
                "DEFE": ("waiting", ""),
            }
        else:
            total, open_ = review_total(), unresolved()
            states = {
                "Inputs": ("done", f"{len(state['complexity'])} complexity file(s)"),
                "Generate": ("done", f"{len(state['files'])} files"),
                "Review gate": (("blocked", f"{open_} unresolved") if open_
                                else ("done", "no cases" if total == 0
                                      else f"{total} resolved")),
                "DEFE": (("done", "ready") if state["defe"]
                         else ("current", "") if open_ == 0
                         else ("waiting", "")),
            }
        for name, (step_state, note) in states.items():
            c.set_step(name, step_state, note)
        views["kpis"].refresh()
        show_envelope()
        c.recheck()

    def refresh(*names: str) -> None:
        for name in names:
            views[name].refresh()
        sync()

    # ------------------------------------------------------------ store
    def persist(mutate) -> bool:
        """Write the review through the store under the engineer's name.
        A save against a revision someone else has moved past is refused
        and said so — never merged silently."""
        resolutions = mutate(dict(state["stored"].get("resolutions", {})))
        try:
            path = store.save({"resolutions": resolutions}, by=c.who(),
                              expected_revision=state["revision"])
        except store.StaleWrite as other:
            ui.notify(f"Not saved — this review was changed by "
                      f"{other.by or 'someone else'} at {other.at}. Reload the "
                      "page to pick up their version before continuing.",
                      type="negative", multi_line=True, close_button=True)
            return False
        except Exception as exc:  # noqa: BLE001 — never block the workbench
            ui.notify(f"Could not save the review: {exc}", type="warning")
            return False
        fresh = store.load(path)
        env = store.envelope(fresh)
        state["stored"] = fresh
        state.update(revision=env["revision"], saved_by=env["by"], saved_at=env["at"])
        show_envelope()
        return True

    def restore_resolutions() -> None:
        """What the store holds for this bundle's cases — matched by the
        programme tag and the engine's ReviewID, never by run."""
        r = state["result"]
        fresh = store.load()
        env = store.envelope(fresh)
        state["stored"] = fresh
        state.update(revision=env["revision"], saved_by=env["by"], saved_at=env["at"])
        review_df = r["review_df"]
        ids = [str(rid) for rid in review_df["ReviewID"]] if len(review_df) else []
        allowed = {str(case["ReviewID"]): review_engine.allowed_pns(case)
                   for _, case in review_df.iterrows()}
        found = store.restore(fresh.get("resolutions", {}), r["my"], r["program"],
                              ids, allowed=allowed)
        state["resolutions"] = {rid: rec["pn"] for rid, rec in found.items()}
        state["notes"] = {rid: rec["note"] for rid, rec in found.items()}
        state["decided"] = {rid: (rec["by"], rec["at"]) for rid, rec in found.items()}

    # ------------------------------------------------------------ shell
    with c.frame("VBOM Risk Matrix",
                 "DoAll / BuildSpec + harness complexity files → the VBOM "
                 "workbook bundle, with a review gate before the DEFE."):
        envelope = c.envelope("")
        c.step_bar(*STEPS)

        @ui.refreshable
        def kpi_view() -> None:
            r = state["result"]
            if r is None:
                return
            total, resolved = review_total(), len(state["resolutions"])
            open_ = total - resolved
            with c.kpi_strip():
                c.kpi(len(r["vin_matrix_df"]), "VINs")
                c.kpi(total, "Review cases", "high" if total else "ok")
                c.kpi(resolved, "Resolved", "ok" if resolved else None)
                c.kpi(open_, "Unresolved", "blocker" if open_ else "ok")
                c.kpi(len(state["files"]), "Files generated")

        views["kpis"] = kpi_view
        kpi_view()
        _guide()

        # ------------------------------------------------- 1 · Inputs
        with c.section("Inputs",
                       "The model year and program name every output file, "
                       "so they must match the BuildSpec / DoAll.",
                       step="Inputs"):
            with ui.row().classes("w-full gap-4 flex-wrap items-start"):
                with ui.column().classes("gap-0"):
                    my = ui.input("Model year", placeholder="26").classes("w-36") \
                        .props("dense").mark("vbom-my")
                    ui.label("Two digits, e.g. 26 (2026 also works)").classes("sx-caption")
                with ui.column().classes("gap-0"):
                    program = ui.input("Program", placeholder="RU").classes("w-36") \
                        .props("dense").mark("vbom-program")
                    ui.label("Program code as it appears in the outputs, e.g. RU") \
                        .classes("sx-caption")
                with ui.column().classes("gap-0"):
                    source = ui.select(["DoAll", "BuildSpec"], value="DoAll",
                                       label="Input type").classes("w-36") \
                        .props("dense").mark("vbom-source")
                    ui.label("Which layout the vehicle file uses").classes("sx-caption")
            my.on_value_change(lambda _e: sync())
            program.on_value_change(lambda _e: sync())
            with ui.row().classes("w-full gap-4 flex-wrap"):
                c.upload_row("DoAll / BuildSpec file",
                             lambda n, b: state.update(input=_Upload(n, b)),
                             accept=".xlsx,.xlsm,.xls")
                c.upload_row("Harness complexity file(s)",
                             lambda n, b: state["complexity"].append(_Upload(n, b)),
                             accept=".xlsx,.xlsm,.xls", multiple=True)

        # ----------------------------------------------- 2 · Generate
        with c.section("Generate",
                       "The master complexity, VIN matrix, selections and the "
                       "macro-enabled review workbook — plus a README, zipped "
                       "for forwarding.",
                       step="Generate"):
            c.action("Generate VBOM bundle", lambda: generate(), needs=missing_inputs)
            # Filled by run_engine_progress while the workflow runs; a long
            # VBOM run is minutes of silence otherwise.
            progress_box = ui.column().classes("w-full gap-1")

            @ui.refreshable
            def files_view() -> None:
                if not state["zip"]:
                    c.empty("The generated files appear here. The bundle "
                            "includes the macro-enabled review workbook — "
                            "resolve in Excel there, or in the review gate below.",
                            icon="folder_zip")
                    return
                with ui.row().classes("w-full gap-6 flex-wrap items-start"):
                    with ui.column().classes("gap-1"):
                        for name in state["files"]:
                            ui.label(name).classes("text-sm sx-mono sx-muted")
                    with ui.row().classes("gap-2 items-center flex-wrap"):
                        c.downloads([(name, lambda n=name: state["files"][n])
                                     for name in state["files"]],
                                    label=f"{len(state['files'])} files")
                        c.download(BUNDLE_NAME, lambda: state["zip"])

            views["files"] = files_view
            files_view()

        # -------------------------------------------- 3 · Review gate
        with c.section("Review gate",
                       "The DEFE template is withheld until every flagged "
                       "selection has a decision — same rule as the Excel "
                       "workbook's macro. Decisions are saved as you make them.",
                       step="Review gate"):

            @ui.refreshable
            def review_view() -> None:
                r = state["result"]
                if r is None:
                    c.empty("Generate the bundle first; the selections the "
                            "engine is unsure about are listed here for a decision.",
                            icon="rule")
                    return
                review_df = r["review_df"]
                total, resolved = len(review_df), len(state["resolutions"])
                if total == 0:
                    c.chip("ok", "No uncertain selections — the DEFE template "
                                 "is ready to generate")
                    return
                ok, open_c = theme.STATUS["ok"], theme.STATUS["high"]
                with ui.row().classes("w-full h-2 rounded-full overflow-hidden gap-0 no-wrap") \
                        .style(f"background:{theme.wash(open_c)}"):
                    if resolved:
                        ui.element("div").classes("h-full") \
                            .style(f"background:{ok};width:{resolved / total * 100:.1f}%")
                    if total - resolved:
                        ui.element("div").classes("h-full") \
                            .style(f"background:{open_c};"
                                   f"width:{(total - resolved) / total * 100:.1f}%")
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    ui.label(f"{resolved} of {total} review cases resolved").classes("sx-caption")
                    c.chip("ok" if resolved == total else "high",
                           "all resolved" if resolved == total
                           else f"{total - resolved} open")
                with ui.row().classes("gap-2 flex-wrap"):
                    for reason, n in review_engine.reason_counts(review_df).items():
                        c.chip("high", f"{n} · {reason}")
                for _, case in review_df.iterrows():
                    review_case(case)

            views["review"] = review_view
            review_view()

        def review_case(case) -> None:
            rid = str(case["ReviewID"])
            resolved_pn = state["resolutions"].get(rid)
            options = review_engine.allowed_pns(case)
            with ui.expansion().classes("w-full").props("dense") as exp:
                with exp.add_slot("header"):
                    with ui.row().classes("items-center gap-3 w-full py-1 flex-wrap"):
                        c.chip("ok" if resolved_pn else "high",
                               f"resolved · {resolved_pn}" if resolved_pn else "open")
                        ui.label(f"{case['VIN']}").classes("text-sm sx-mono")
                        ui.label(str(case["HarnessFamily"])) \
                            .classes("text-sm font-semibold")
                        ui.label(str(case["ReviewReason"])).classes("sx-caption")
                for label, key in [("Engine recommendation", "EngineRecommendation"),
                                   ("Required codes", "RequiredSalesCodes"),
                                   ("Missing codes", "MissingSalesCodes"),
                                   ("Extra codes", "ExtraSalesCodes"),
                                   ("Giveaway", "Giveaway")]:
                    value = str(case.get(key) or "").strip()
                    if value:
                        with ui.row().classes("gap-2 no-wrap"):
                            ui.label(label).classes("sx-caption w-40 shrink-0")
                            ui.label(value).classes("text-xs sx-mono")
                details = str(case.get("CandidateDetails") or "")
                if details:
                    ui.label(details).classes(
                        "text-xs sx-mono p-2 rounded w-full whitespace-pre-line") \
                        .style(f"background:{theme.CANVAS}")
                pn_sel = ui.select(options,
                                   value=resolved_pn if resolved_pn in options
                                   else (case["EngineRecommendation"]
                                         if case["EngineRecommendation"] in options
                                         else None),
                                   label="Resolved PN").classes("w-64") \
                    .props("dense").mark("vbom-pn-" + "".join(rid.split()))
                note_in = ui.input("Reviewer note",
                                   value=state["notes"].get(rid, "")) \
                    .classes("w-full").props("dense")
                decided = state["decided"].get(rid)
                if resolved_pn and decided and (decided[0] or decided[1]):
                    ui.label(f"Decided by {decided[0] or 'unknown'} · {decided[1][:16]}") \
                        .classes("sx-caption")

                def resolve(rid=rid, pn_sel=pn_sel, note_in=note_in) -> None:
                    pn, note = pn_sel.value, note_in.value or ""
                    r = state["result"]
                    if not persist(lambda res: store.remember(
                            res, r["my"], r["program"], rid, pn, note, by=c.who())):
                        return
                    state["resolutions"][rid] = pn
                    state["notes"][rid] = note
                    state["decided"][rid] = (c.who(), state["saved_at"])
                    state["defe"] = None  # decisions changed; regenerate
                    refresh("review", "defe")

                def reopen(rid=rid) -> None:
                    r = state["result"]
                    if not persist(lambda res: store.forget(
                            res, r["my"], r["program"], rid)):
                        return
                    state["resolutions"].pop(rid, None)
                    state["decided"].pop(rid, None)
                    state["defe"] = None
                    refresh("review", "defe")

                with ui.row().classes("gap-2"):
                    resolve_btn = ui.button("Resolve", icon="check", on_click=resolve) \
                        .props("outline dense no-caps")
                    # a PN is the decision; without one there is nothing to save
                    resolve_btn.bind_enabled_from(pn_sel, "value", backward=bool)
                    reopen_btn = ui.button("Reopen", icon="undo", on_click=reopen) \
                        .props("flat dense no-caps")
                    reopen_btn.set_enabled(bool(resolved_pn))

        # ---------------------------------------------------- 4 · DEFE
        with c.section("DEFE",
                       "The DEFE template is built by the same routine the "
                       "review workbook's macro runs, with your resolutions applied.",
                       step="DEFE"):

            @ui.refreshable
            def defe_view() -> None:
                r = state["result"]
                name = r["defe_output_name"] if r is not None else "DEFE template"
                with ui.row().classes("items-center gap-3 flex-wrap"):
                    c.action(f"Generate {name}", lambda: make_defe(),
                             needs=missing_for_defe, icon="assignment_turned_in")
                    if state["defe"]:
                        c.download(state["defe"][0], lambda: state["defe"][1])

            views["defe"] = defe_view
            defe_view()

        # ------------------------------------------------------ engines
        async def make_defe() -> None:
            r = state["result"]

            def work():
                resolved_df = review_engine.apply_resolutions(
                    r["selections_df"], state["resolutions"])
                return review_engine.generate_defe(
                    r["my"], r["program"], resolved_df, r["vin_matrix_df"])

            out = await c.run_engine(work, running="Generating the DEFE template…",
                                     done="DEFE template ready")
            if out is not None:
                state["defe"] = out
                refresh("defe")

        async def generate() -> None:
            my_text, program_text, source_text = my_value(), program_value(), source.value

            def work(report):
                from splice.vbom import guide, run_vbom_workflow
                with tempfile.TemporaryDirectory(prefix="ng_vbom_") as td:
                    result = run_vbom_workflow(
                        my=my_text, program=program_text,
                        source_type=source_text,
                        input_upload=state["input"],
                        complexity_uploads=list(state["complexity"]),
                        output_dir=Path(td),
                        progress=report,
                    )
                    buf, files = io.BytesIO(), {}
                    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                        for key in ("master_path", "vin_matrix_path",
                                    "selections_path", "review_path"):
                            path = result.get(key)
                            if path and Path(path).is_file():
                                zf.write(path, arcname=Path(path).name)
                                files[Path(path).name] = Path(path).read_bytes()
                        # The bundle gets emailed on, so it carries its own
                        # instructions rather than relying on this page.
                        readme = guide.bundle_readme(
                            f"{result['my'][-2:]}_{result['program']}",
                            result.get("defe_output_name", ""),
                            result.get("review_case_count", 0))
                        zf.writestr(guide.README_FILENAME, readme)
                        files[guide.README_FILENAME] = readme.encode("utf-8")
                    return result, buf.getvalue(), files

            out = await c.run_engine_progress(
                work, progress_box, running="Running the VBOM workflow…",
                done="VBOM bundle ready")
            if out is not None:
                state["result"], state["zip"], state["files"] = out
                state["defe"] = None
                restore_resolutions()
                refresh("files", "review", "defe")

        sync()
