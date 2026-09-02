"""The two long-running actions: load the files, run the analysis.

Both run their engine work off the event loop with a progress bar, then
update the workbench and refresh the cards that changed.
"""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app.pages.circuit_applicability.workbench import Workbench
from splice.dtxcircuits import analyze_harness, correspond, read_dtx_circuits
from splice.dtxcircuits import chart as chart_mod
from splice.dtxcircuits import integrity, store
from splice.dtxcircuits import report as report_mod
from splice.dtxcircuits.complexity import read_harness_file


async def load(wb: Workbench) -> None:
    state = wb.state
    if not state["dtx"] or not state["uploads"]:
        ui.notify("Load the DTx and at least one complexity file",
                  type="warning")
        return

    def work(report):
        report(0.05, "Reading the DTx…")
        name, data = state["dtx"]
        rows, meta = read_dtx_circuits(data, name)

        harnesses, metas, failed = {}, {}, []
        total = len(state["uploads"])
        for i, (fname, payload) in enumerate(state["uploads"].items(), 1):
            report(0.1 + 0.7 * (i - 1) / total,
                   f"Reading complexity {i} of {total} — {fname}")
            try:
                harness, cmeta = read_harness_file(payload, fname)
            except Exception as exc:
                failed.append(f"{fname}: {exc}")
                continue
            harnesses[fname] = harness
            metas[fname] = cmeta

        report(0.80, "Checking the Sales Code column…")
        issues = integrity.scan(rows)

        report(0.85, "Checking programme and phase…")
        corr = correspond.check(meta, list(metas.values()))

        report(0.92, "Auto-matching families…")
        families = sorted({r.harness_family for r in rows})
        counts = {f: sum(1 for r in rows if r.harness_family == f)
                  for f in families}
        from splice.dtxcircuits import matching
        exact = matching.auto_map(
            families,
            {f: (metas[f].harness or harnesses[f].name) for f in harnesses})
        # a family holds a LIST of harnesses; auto-connect seeds one
        mapping = {family: [filename] for family, filename in exact.items()}
        # a mapping the SE built in an earlier session wins over the
        # automatic one — it was a decision, this is only a guess
        identity_of = {f: store.harness_identity(
                           harnesses[f].def_id,
                           metas[f].harness or harnesses[f].name)
                       for f in harnesses}
        restored = store.restore_mapping(
            state["stored"].get("mapping", {}), identity_of)
        mapping.update(restored)
        report(1.0, "Done")
        return (rows, meta, [(f, counts[f]) for f in families],
                harnesses, metas, mapping, corr, failed, len(restored),
                issues)

    out = await c.run_engine_progress(
        work, wb.progress, running="Reading files…", done="Files loaded")
    if out is None:
        return
    (rows, meta, families, harnesses, metas, mapping, corr, failed,
     restored_count, issues) = out
    state.update(rows=rows, dtx_meta=meta, families=families,
                 harnesses=harnesses, metas=metas, mapping=mapping,
                 corr=corr, entries=[], charts=[], selected=None,
                 issues=issues)
    if restored_count:
        ui.notify(f"Restored {restored_count} mapping(s) from your last "
                  "session", type="info")
    # a repair confirmed on an earlier DTx applies to any later one
    # repeating the same text — say so, or it happens invisibly
    carried = sum(1 for i in issues if i.expression in state["fixes"])
    if carried:
        ui.notify(f"{carried} sales-code repair(s) carried over from an "
                  "earlier session and were applied to this DTx",
                  type="info", multi_line=True)
    for problem in failed[:5]:
        ui.notify(problem, type="negative", multi_line=True,
                  close_button=True)
    ui.notify(f"{len(mapping)} of {len(families)} families matched "
              "automatically", type="positive")
    wb.measure()
    wb.refresh("integrity", "mapping", "results")


def _conditions_by(rows, attribute: str) -> dict:
    """Condition per circuit (or per CNUM) exactly as the DTx stated it."""
    from splice.dtxcircuits.analyze import union_condition
    grouped: dict = {}
    for row in rows:
        key = getattr(row, attribute, "")
        if key:
            grouped.setdefault(key, []).append(row)
    return {key: (union_condition(group) or "")
            for key, group in grouped.items()}


async def run(wb: Workbench) -> None:
    state = wb.state
    if not any(state["mapping"].values()):
        ui.notify("Connect at least one family first", type="warning")
        return

    def work(report):
        # repairs first: an unfixed expression is false everywhere and
        # would make its circuits read as never built
        raw_rows = state["rows"]
        rows = integrity.apply_fixes(raw_rows, state["fixes"])
        pairs = [(family, filename)
                 for family, files in sorted(state["mapping"].items())
                 for filename in files]
        out = []
        for index, (family, filename) in enumerate(pairs, start=1):
            harness = state["harnesses"][filename]
            label = (state["metas"][filename].harness or harness.name)
            report(index / max(len(pairs), 1),
                   f"Resolving {family} → {label} "
                   f"({index} of {len(pairs)})…")
            family_rows = [r for r in rows if r.harness_family == family]
            analysis = analyze_harness(family_rows, harness,
                                       harness_name=label)
            # the same unions over the UNREPAIRED rows, so the export can
            # show what the DTx said next to what was analysed
            original = [r for r in raw_rows if r.harness_family == family]
            out.append(report_mod.Entry(
                label=f"{family} → {label}", family=family,
                filename=filename, analysis=analysis,
                original_circuit_conditions=_conditions_by(original, "circuit"),
                original_cnum_conditions=_conditions_by(original, "cnum"),
                complexity=harness))
        return out

    out = await c.run_engine_progress(
        work, wb.progress, running="Analyzing…", done="Analysis ready")
    if out is not None:
        state["entries"] = out
        state["selected"] = None
        # Never-built circuits and connectors, and every sales-code
        # gap, go into the review by default — they are exactly what
        # the customer has to fix in the next export. Anything the SE
        # has explicitly unticked stays out.
        state["charts"] = chart_mod.build_charts(
            out, integrity.apply_fixes(state["rows"], state["fixes"]))
        picked = report_mod.auto_select(out, state["dismissed"])
        added = [k for k in picked if k not in state["cleanup"]]
        state["cleanup"].update({k: v for k, v in picked.items()
                                 if k in added})
        if added:
            ui.notify(f"{len(added)} finding(s) added to the review "
                      "automatically — untick any you do not want the "
                      "customer to see", type="info", multi_line=True)
        wb.persist()
        wb.measure()
        wb.refresh("chart")
        # Selections are NOT pruned to this run. A tick made against a
        # family that is not mapped today is still a real cleanup task,
        # and dropping it here would quietly delete it from the store.
        wb.refresh("results")
