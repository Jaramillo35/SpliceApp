"""Inline Comment Carryover — past comments into the new inline report.

Workbench archetype: Inputs → Review → Generate, a KPI strip derived from the
result, and one gated primary per step. The judgement lives in
``splice.inline.carryover``; this page shows it and records decisions.

The review is a gate. Identical rows are copied without asking and hidden
behind a switch; a row whose sales codes changed shows the old comment as a
suggestion; a row that changed in any other way suggests nothing. The report
is not written until every row that needs a decision has one.

The download is handed over undressed: the Downloads helper adds a Read Me
sheet and restyles headers for the toolkit's own workbooks, and an inline
report has to come back in exactly the format it arrived in.
"""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from splice.inline import carryover as co

STEPS = ("Inputs", "Review", "Generate")
LABEL_TO_DECISION = {label: key for key, label in co.DECISION_LABEL.items()}
UNDECIDED = "— choose —"


@ui.page("/inline-comments")
def page() -> None:
    state: dict = {
        "old": None, "new": None,        # (filename, bytes)
        "result": None,                  # co.Carryover
        "output": None,                  # (filename, bytes)
        "show_exact": False,
    }
    views: dict = {}

    def refresh(*names: str) -> None:
        for name in names:
            views[name].refresh()
        sync()

    def sync() -> None:
        res = state["result"]
        if res is None:
            steps = {"Inputs": ("current", ""), "Review": ("waiting", ""),
                     "Generate": ("waiting", "")}
        else:
            n = res.counts()
            steps = {
                "Inputs": ("done", f"{len(res.proposals) + n['lost']} comments found"),
                "Review": (("current", f"{n['undecided']} to decide")
                           if n["undecided"] else ("done", "all decided")),
                "Generate": (("done", "written") if state["output"]
                             else ("current", "") if not n["undecided"]
                             else ("waiting", "")),
            }
        for name, (st, note) in steps.items():
            c.set_step(name, st, note)
        views["kpis"].refresh()
        c.recheck()

    with c.frame("Inline Comment Carryover",
                 "Comments from a past inline report, copied into the new one — "
                 "identical rows automatically, changed rows through review."):
        c.step_bar(*STEPS)

        # ----------------------------------------------------------- KPIs
        @ui.refreshable
        def kpi_view() -> None:
            res = state["result"]
            if res is None:
                return
            n = res.counts()
            pending_codes = sum(1 for p in res.undecided if p.kind == co.SALES_CODE)
            pending_changed = sum(1 for p in res.undecided if p.kind == co.CHANGED)
            with c.kpi_strip():
                c.kpi(n[co.EXACT], "Copied as-is", "ok", hint="identical rows")
                c.kpi(n[co.SALES_CODE], "Sales code changed",
                      "review" if pending_codes else None,
                      hint="old comment suggested")
                c.kpi(n[co.CHANGED], "Row changed",
                      "review" if pending_changed else None,
                      hint="nothing suggested")
                c.kpi(n["undecided"], "Still to decide",
                      "review" if n["undecided"] else "ok")
                c.kpi(n["lost"], "Comments with no row", "high" if n["lost"] else None,
                      hint="listed under the review")

        views["kpis"] = kpi_view
        kpi_view()

        # --------------------------------------------------------- Inputs
        with c.section("Inputs",
                       "The OLD report is the one your comments are in; the NEW "
                       "report is this release's, comments empty. Both are the "
                       "same inline report format — the INLINES index and one sheet "
                       "per inline pair.", step="Inputs"):
            c.upload_row("OLD inline report — with comments",
                         lambda n, b: state.update(old=(n, b), result=None, output=None),
                         accept=".xlsx,.xlsm")
            c.upload_row("NEW inline report",
                         lambda n, b: state.update(new=(n, b), result=None, output=None),
                         accept=".xlsx,.xlsm")
            c.action("Match comments", lambda: run_match(),
                     needs=lambda: [label for label, key in
                                    (("the OLD report", "old"), ("the NEW report", "new"))
                                    if not state[key]],
                     icon="compare_arrows")

        # --------------------------------------------------------- Review
        @ui.refreshable
        def review_view() -> None:
            res = state["result"]
            with c.section("Review",
                           "Every comment that needs your judgement. A sales-code "
                           "change suggests the old comment; any other change "
                           "suggests nothing, because a comment like 'WIRE TYPE "
                           "OK' may no longer be true. Pick a decision, or type in "
                           "'Comment written' to write your own.", step="Review"):
                if res is None:
                    c.empty("Match the two reports — the comments that need a "
                            "decision land here.", icon="rate_review")
                    return
                for note in res.notes:
                    c.note("info", note)
                _bulk(res)
                _grid(res)
                _lost(res)

        def _bulk(res) -> None:
            suggestions = [p for p in res.undecided if p.suggested]
            changed = [p for p in res.undecided if p.kind == co.CHANGED]
            exact = res.of_kind(co.EXACT)
            with ui.row().classes("gap-2 flex-wrap items-center"):
                if suggestions:
                    ui.button(f"Copy old comment on {len(suggestions)} sales-code "
                              "change(s)", icon="done_all",
                              on_click=lambda: bulk(lambda: res.accept_suggestions())) \
                        .props("outline dense no-caps")
                if changed:
                    ui.button(f"Leave {len(changed)} changed row(s) blank",
                              icon="remove_done",
                              on_click=lambda: bulk(
                                  lambda: res.decide_all(co.CHANGED, co.BLANK))) \
                        .props("outline dense no-caps")
                if exact:
                    ui.switch(f"Show the {len(exact)} identical row(s) copied without "
                              "asking", value=state["show_exact"],
                              on_change=lambda v: (state.update(show_exact=bool(v.value)),
                                                   refresh("review")))

        def _row(p) -> dict:
            return {
                "_id": p.id,
                "Status": "Decided" if p.decided else "To decide",
                "Kind": co.KIND_LABEL[p.kind],
                "Sheet": p.sheet,
                "Pin": p.pin,
                "Circuit": f"{p.circuit1 or '—'} / {p.circuit2 or '—'}",
                "What changed": p.changed or "identical",
                "Old comment": p.old_comment + (
                    f"  (also matched: {'; '.join(p.alternatives)})"
                    if p.alternatives else ""),
                "Decision": co.DECISION_LABEL.get(p.decision or "", UNDECIDED),
                "Comment written": p.result if p.decided else "",
            }

        def _grid(res) -> None:
            shown = [p for p in res.proposals
                     if state["show_exact"] or p.kind != co.EXACT or p.existing]
            if not shown:
                c.note("ok", "Every comment carried to an identical row — nothing "
                             "needs a decision.")
                return
            columns = [
                {"field": "Status", "width": 110, "pinned": "left"},
                {"field": "Kind", "width": 150, "pinned": "left"},
                {"field": "Sheet", "width": 140},
                {"field": "Pin", "width": 70},
                {"field": "Circuit", "width": 140},
                {"field": "What changed", "flex": 1, "minWidth": 260,
                 "tooltipField": "What changed"},
                {"field": "Old comment", "width": 220, "tooltipField": "Old comment"},
                {"field": "Decision", "width": 210, "editable": True,
                 "cellEditor": "agSelectCellEditor",
                 "cellEditorParams": {"values": [UNDECIDED, *co.DECISION_LABEL.values()]}},
                {"field": "Comment written", "width": 240, "editable": True,
                 "tooltipField": "Comment written"},
            ]
            grid = ui.aggrid({
                "columnDefs": columns,
                "rowData": [_row(p) for p in shown],
                ":getRowId": "(params) => params.data._id",
                "defaultColDef": {"resizable": True, "sortable": True,
                                  "suppressMovable": True},
            }).classes("w-full").style("height: 26rem")

            def on_edit(e) -> None:
                data = e.args.get("data") or {}
                column = e.args.get("colId")
                pid = data.get("_id")
                try:
                    p = res.get(pid)
                    if column == "Decision":
                        decision = LABEL_TO_DECISION.get(data.get("Decision"))
                        if decision is None:
                            res.undo(pid)
                        elif decision == co.NEW:
                            res.decide(pid, co.NEW, str(data.get("Comment written") or ""))
                        else:
                            res.decide(pid, decision)
                    elif column == "Comment written":
                        text = str(data.get("Comment written") or "").strip()
                        if not text:
                            res.decide(pid, co.BLANK)
                        elif text != (p.result or ""):
                            res.decide(pid, co.NEW, text)
                except (KeyError, ValueError) as exc:
                    ui.notify(f"{exc}. Type the comment in 'Comment written' to "
                              "write a new one." if "text" in str(exc) else str(exc),
                              type="warning")
                if pid:
                    try:
                        grid.run_grid_method("applyTransaction",
                                             {"update": [_row(res.get(pid))]})
                    except KeyError:
                        pass
                state["output"] = None
                refresh("generate")

            grid.on("cellValueChanged", on_edit)

        def _lost(res) -> None:
            if not res.lost:
                return
            with ui.expansion(f"Comments with no row in the new report ({len(res.lost)})") \
                    .classes("w-full").props("dense"):
                ui.label("These comments were not carried: nothing in the new "
                         "report has their pin and circuit. Re-place any that still "
                         "matter by hand.").classes("sx-caption")
                c.frame_table([{"sheet": x.sheet, "pin": x.pin,
                                "circuit": f"{x.circuit1 or '—'} / {x.circuit2 or '—'}",
                                "comment": x.comment, "why": x.reason}
                               for x in res.lost],
                              labels={"sheet": "Sheet", "pin": "Pin",
                                      "circuit": "Circuit", "comment": "Old comment",
                                      "why": "Why it did not carry"})

        views["review"] = review_view
        review_view()

        # ------------------------------------------------------- Generate
        @ui.refreshable
        def generate_view() -> None:
            with c.section("Generate",
                           "The NEW report with the decided comments written. Every "
                           "other cell, link, frozen pane and filter is exactly as "
                           "it arrived; a copied comment keeps its highlight.",
                           step="Generate"):
                def needs() -> list[str]:
                    res = state["result"]
                    if res is None:
                        return ["a match of the two reports"]
                    n = len(res.undecided)
                    return [f"a decision on {n} row(s)"] if n else []

                c.action("Write the commented report", lambda: generate(),
                         needs=needs, icon="edit_note")
                if state["output"]:
                    name, data = state["output"]
                    n = state["result"].counts()["written"]
                    c.note("ok", f"{n} comment(s) written into {name}.")
                    c.download(name, lambda d=data: d, dress=False)

        views["generate"] = generate_view
        generate_view()
        sync()

    # ---------------------------------------------------------- actions
    async def run_match() -> None:
        old_name, old_data = state["old"]
        new_name, new_data = state["new"]

        def work():
            return co.match(co.read_report(old_data, old_name),
                            co.read_report(new_data, new_name))

        result = await c.run_engine(work, running="Matching comments…",
                                    done="Comments matched")
        if result is None:
            return
        state.update(result=result, output=None, show_exact=False)
        refresh("review", "generate")

    def bulk(action) -> None:
        action()
        state["output"] = None
        refresh("review", "generate")

    async def generate() -> None:
        res = state["result"]
        if res is None or res.undecided:
            return   # the action is gated; this is only a guard
        old_name, old_data = state["old"]
        new_name, new_data = state["new"]
        keep_vba = new_name.lower().endswith(".xlsm")
        data = await c.run_engine(co.apply, old_data, new_data, res, keep_vba,
                                  running="Writing comments…", done="Report written")
        if data is None:
            return
        state["output"] = (co.output_name(new_name), data)
        refresh("generate")
