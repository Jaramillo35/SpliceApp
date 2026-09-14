"""Inline Comment Carryover — past comments into the new inline report.

Workbench archetype: Inputs → Review → Generate, a KPI strip derived from the
result, and one gated primary per step. The judgement lives in
``splice.inline.carryover``; this page shows it and records decisions.

The review is a gate, built for attention rather than throughput:

* **A queue, likeliest-wrong first.** A comment that names what changed
  ('Check size' after the size moved), or sits on a wire that lost a side, is
  shown before one whose change is elsewhere; sales-code rows follow; comments
  with no row in the new report come last — and block the report until
  someone has looked at each one.
* **One decision card.** The selected row shows its changes as old and new,
  marks the ones the comment talks about, quotes the comment, and offers the
  decisions as buttons with a key each. Deciding moves to the next open row;
  nothing in the list moves under the reader; every decision can be undone.
* **Bulk only where it is safe.** The old comment can be copied onto every
  sales-code row whose comment is not about the variant. There is no bulk
  path through a row whose wire changed: that row is what the gate is for.

The download is handed over undressed: the Downloads helper adds a Read Me
sheet and restyles headers for the toolkit's own workbooks, and an inline
report has to come back in exactly the format it arrived in.
"""

from __future__ import annotations

import contextlib

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme
from splice.inline import carryover as co

STEPS = ("Inputs", "Review", "Generate")

#: what a decided item says about itself in the queue
DONE_LABEL = {co.COPY: "Copied", co.NEW: "New comment", co.BLANK: "Left blank",
              co.KEEP: "Kept its own", co.REPLACE: "Re-place by hand",
              co.OBSOLETE: "No longer applies"}
#: one key per decision; the arrows move and U undoes
KEYS = {"c": co.COPY, "w": co.NEW, "b": co.BLANK, "k": co.KEEP,
        "r": co.REPLACE, "x": co.OBSOLETE}
FILTERS = (("open", "To decide"), ("done", "Decided"), ("all", "All"))


def _circuit(item) -> str:
    one, two = item.circuit1 or "", item.circuit2 or ""
    if one and one == two:
        return one
    return f"{one or '—'} / {two or '—'}"


def _comment(item) -> str:
    return item.comment if isinstance(item, co.Lost) else item.old_comment


@ui.page("/inline-comments")
def page() -> None:
    state: dict = {
        "old": None, "new": None,        # (filename, bytes)
        "result": None,                  # co.Carryover
        "output": None,                  # (filename, bytes)
        "selected": None,                # id of the item on the decision card
        "filter": "open",
        "writing": None,                 # id whose new comment is being typed
        "history": [],                   # (snapshot, selected), newest last
    }
    views: dict = {"row_ids": {}}

    # ------------------------------------------------------------ plumbing
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
            waiting = res.blocking
            steps = {
                "Inputs": ("done", f"{len(res.proposals) + n['lost']} comments found"),
                "Review": (("current", f"{waiting} to decide") if waiting
                           else ("done", "all decided")),
                "Generate": (("done", "written") if state["output"]
                             else ("current", "") if not waiting
                             else ("waiting", "")),
            }
        for name, (st, note) in steps.items():
            c.set_step(name, st, note)
        views["kpis"].refresh()
        c.recheck()

    def visible(res) -> list:
        if state["filter"] == "open":
            return [x for x in res.queue() if not x.decided]
        items = res.queue(include_settled=True)
        if state["filter"] == "done":
            return [x for x in items if x.decided]
        return items

    def find(res, item_id: str):
        if item_id.endswith("!lost"):
            return res.get_lost(item_id)
        return res.get(item_id)

    def next_open(res, current: str | None) -> str | None:
        """The next item still waiting, after ``current`` in queue order."""
        order = res.queue()
        ids = [x.id for x in order]
        start = ids.index(current) + 1 if current in ids else 0
        for item in order[start:] + order[:start]:
            if not item.decided:
                return item.id
        return None

    def reveal() -> None:
        """Keep the selected row in view when the keyboard moves the card."""
        element_id = views["row_ids"].get(state["selected"])
        if element_id is None:
            return
        # a scroll is cosmetic; the simulated client has no browser to run it
        with contextlib.suppress(Exception):
            ui.run_javascript(f"document.getElementById('c{element_id}')"
                              "?.scrollIntoView({block: 'nearest'})")

    # ------------------------------------------------------------- deciding
    def snapshot(res, ids) -> list:
        shots = []
        for item_id in ids:
            item = find(res, item_id)
            if isinstance(item, co.Lost):
                shots.append(("lost", item_id, item.ack, ""))
            else:
                shots.append(("row", item_id, item.decision, item.text))
        return shots

    def remember(res, ids, selected) -> None:
        state["history"].append((snapshot(res, ids), selected))

    def undo() -> None:
        res = state["result"]
        if res is None or not state["history"]:
            return
        shots, selected = state["history"].pop()
        for kind, item_id, value, text in shots:
            if kind == "lost":
                if value is None:
                    res.unacknowledge(item_id)
                else:
                    res.acknowledge(item_id, value)
            elif value is None:
                res.undo(item_id)
            else:
                res.decide(item_id, value, text)
        state.update(selected=selected, writing=None, output=None)
        refresh("review", "generate")
        reveal()

    def decide(pid: str, decision: str, text: str = "") -> None:
        res = state["result"]
        remember(res, [pid], pid)
        try:
            res.decide(pid, decision, text)
        except ValueError as exc:
            state["history"].pop()
            ui.notify(str(exc), type="warning")
            return
        state.update(writing=None, output=None, selected=next_open(res, pid) or pid)
        refresh("review", "generate")
        reveal()

    def acknowledge(lid: str, ack: str) -> None:
        res = state["result"]
        remember(res, [lid], lid)
        res.acknowledge(lid, ack)
        state.update(output=None, selected=next_open(res, lid) or lid)
        refresh("review", "generate")
        reveal()

    def save_new(pid: str, text: str) -> None:
        if not (text or "").strip():
            ui.notify("Type the comment, or choose Leave blank.", type="warning")
            return
        decide(pid, co.NEW, text)

    def start_writing(pid: str) -> None:
        state.update(writing=pid, selected=pid)
        refresh("review")

    def stop_writing() -> None:
        state["writing"] = None
        refresh("review")

    def bulk_copy(ids) -> None:
        res = state["result"]
        remember(res, ids, state["selected"])
        for item_id in ids:
            res.decide(item_id, co.COPY)
        state["output"] = None
        refresh("review", "generate")

    def bulk_acknowledge(ids, ack: str) -> None:
        res = state["result"]
        remember(res, ids, state["selected"])
        for item_id in ids:
            res.acknowledge(item_id, ack)
        state["output"] = None
        refresh("review", "generate")

    def select(item_id: str) -> None:
        state.update(selected=item_id, writing=None)
        refresh("review")

    def set_filter(key: str) -> None:
        state["filter"] = key
        refresh("review")

    def move(step: int) -> None:
        res = state["result"]
        if res is None:
            return
        ids = [x.id for x in visible(res)]
        if not ids:
            return
        here = ids.index(state["selected"]) if state["selected"] in ids else -1
        state.update(selected=ids[max(0, min(len(ids) - 1, here + step))], writing=None)
        refresh("review")
        reveal()

    def on_key(e) -> None:
        if not e.action.keydown or e.modifiers.ctrl or e.modifiers.meta or e.modifiers.alt:
            return
        res = state["result"]
        if res is None:
            return
        name = e.key.name
        if name in ("ArrowDown", "ArrowUp"):
            move(1 if name == "ArrowDown" else -1)
            return
        if e.action.repeat:                  # a held key must not decide twice
            return
        key = name.lower() if len(name) == 1 else ""
        if key == "u":
            undo()
            return
        selected = state["selected"]
        if key not in KEYS or selected is None:
            return
        decision = KEYS[key]
        lost_card = selected.endswith("!lost")
        if lost_card != (decision in (co.REPLACE, co.OBSOLETE)):
            return                           # a row key on a lost card, or the reverse
        if lost_card:
            acknowledge(selected, decision)
        elif decision == co.NEW:
            start_writing(selected)
        elif decision == co.KEEP and not res.get(selected).existing:
            return
        else:
            decide(selected, decision)

    # ------------------------------------------------------------------ page
    with c.frame("Inline Comment Carryover",
                 "Comments from a past inline report, copied into the new one — "
                 "identical rows automatically, changed rows through review."):
        c.step_bar(*STEPS)
        # buttons keep the shortcuts: focus stays on a decision button after a click
        ui.keyboard(on_key=on_key, ignore=["input", "select", "textarea"])

        # ----------------------------------------------------------- KPIs
        @ui.refreshable
        def kpi_view() -> None:
            res = state["result"]
            if res is None:
                return
            n = res.counts()
            recheck = sum(1 for p in res.undecided if p.attention == co.RECHECK)
            with c.kpi_strip():
                c.kpi(n[co.EXACT], "Copied as-is", "ok", hint="identical rows")
                c.kpi(recheck, "To re-check", "high" if recheck else None,
                      hint="the comment names what changed")
                c.kpi(n["undecided"], "Rows to decide",
                      "review" if n["undecided"] else "ok")
                c.kpi(n["unacknowledged"], "Comments to acknowledge",
                      "high" if n["unacknowledged"] else None,
                      hint=f"{n['lost']} with no row in the new report")

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
                           "Every comment that needs your judgement, the likeliest "
                           "to be wrong first. ↑ ↓ move; C copies the old comment, "
                           "W writes a new one, B leaves it blank, K keeps the new "
                           "report's own; U undoes.", step="Review"):
                if res is None:
                    c.empty("Match the two reports — the comments that need a "
                            "decision land here.", icon="rate_review")
                    return
                for note in res.notes:
                    c.note("info", note)
                _gate(res)
                _scoped_bulk(res)
                _filters(res)
                shown = visible(res)
                ids = [x.id for x in shown]
                if state["selected"] not in ids:
                    state["selected"] = ids[0] if ids else None
                with ui.splitter(value=40).classes("w-full") as split:
                    with split.before:
                        with ui.column().classes(
                                "w-full gap-1 pr-3 max-h-[36rem] overflow-y-auto"):
                            _queue(shown)
                    with split.after:
                        with ui.column().classes("w-full gap-3 pl-3"):
                            _card(res)

        def _gate(res) -> None:
            items = res.queue()
            done = sum(1 for x in items if x.decided)
            total = len(items)
            with ui.column().classes("w-full gap-1"):
                with ui.row().classes("w-full items-center justify-between no-wrap"):
                    if res.blocking:
                        parts = []
                        if res.undecided:
                            parts.append(f"{len(res.undecided)} row(s) to decide")
                        if res.unacknowledged:
                            parts.append(f"{len(res.unacknowledged)} comment(s) with "
                                         "no row to acknowledge")
                        ui.label(f"{done} of {total} done — " + " · ".join(parts)) \
                            .classes("text-sm font-semibold")
                    else:
                        ui.label(f"All {total} decided — the report can be written") \
                            .classes("text-sm font-semibold") \
                            .style(f"color:{theme.STATUS_TEXT['ok']}")
                    if state["history"]:
                        with ui.button("Undo", on_click=lambda _e: undo()) \
                                .props('flat dense no-caps aria-keyshortcuts="U"'):
                            ui.label("U").classes("sx-kbd ml-2")
                ui.linear_progress(value=(done / total) if total else 1.0,
                                   show_value=False) \
                    .props("rounded size=6px" + ("" if res.blocking else " color=positive"))

        def _scoped_bulk(res) -> None:
            codes = [p for p in res.undecided if p.group == co.GROUP_CODES and p.suggested]
            lost = res.unacknowledged
            if not (codes or lost):
                return
            with ui.row().classes("gap-2 flex-wrap items-center"):
                if codes:
                    ui.button(f"Copy the suggested comment on {len(codes)} sales-code "
                              "row(s)", icon="done_all",
                              on_click=lambda _e, ids=[p.id for p in codes]: bulk_copy(ids)) \
                        .props("outline dense no-caps")
                if lost:
                    ui.button(f"Mark {len(lost)} comment(s) with no row as no longer "
                              "applying", icon="playlist_remove",
                              on_click=lambda _e, ids=[x.id for x in lost]:
                                  bulk_acknowledge(ids, co.OBSOLETE)) \
                        .props("outline dense no-caps")
                held = sum(1 for p in res.undecided if p.group == co.GROUP_CODES_RECHECK)
                if held:
                    ui.label(f"{held} sales-code row(s) whose comment talks about the "
                             "variant are left for you.").classes("sx-caption")

        def _filters(res) -> None:
            everything = res.queue(include_settled=True)
            counts = {"open": sum(1 for x in res.queue() if not x.decided),
                      "done": sum(1 for x in everything if x.decided),
                      "all": len(everything)}
            with ui.row().classes("items-center gap-2 flex-wrap"):
                ui.label("Show").classes("sx-eyebrow")
                for key, label in FILTERS:
                    c.toggle_chip(label, state["filter"] == key,
                                  lambda k=key: set_filter(k), counts[key])

        def _queue(shown) -> None:
            views["row_ids"] = {}
            if not shown:
                c.empty({"open": "Nothing left to decide.",
                         "done": "Nothing decided yet.",
                         "all": "Nothing to review."}[state["filter"]],
                        icon="task_alt")
                return
            group = None
            for item in shown:
                if item.group != group:
                    group = item.group
                    n = sum(1 for x in shown if x.group == group)
                    ui.label(f"{group} · {n}").classes("text-xs font-semibold sx-muted mt-3")
                _queue_row(item)

        def _queue_row(item) -> None:
            active = state["selected"] == item.id
            lost = isinstance(item, co.Lost)
            row = ui.button(on_click=lambda _e, i=item.id: select(i)) \
                .props(f'flat no-caps align=left aria-pressed="{"true" if active else "false"}"') \
                .classes("rounded px-2 py-1.5 w-full normal-case") \
                .style(f"background:{theme.wash(theme.BRAND)}" if active
                       else f"background:{theme.SURFACE_2}")
            views["row_ids"][item.id] = row.id
            with row:
                with ui.row().classes("items-center gap-2 no-wrap w-full"):
                    ui.icon("check_circle" if item.decided else "radio_button_unchecked") \
                        .classes("text-base shrink-0") \
                        .style(f"color:{theme.STATUS_TEXT['ok'] if item.decided else theme.TEXT_3}")
                    with ui.column().classes("gap-0 min-w-0 grow items-start"):
                        ui.label(f"pin {item.pin} · {_circuit(item)}") \
                            .classes("text-sm font-semibold sx-mono truncate")
                        ui.label(f"{item.sheet} · “{_comment(item)}”") \
                            .classes("text-xs sx-muted truncate")
                    if item.decided:
                        ui.label(DONE_LABEL[item.ack if lost else item.decision]) \
                            .classes("text-xs shrink-0") \
                            .style(f"color:{theme.STATUS_TEXT['ok']}")
                    elif not lost and item.attention == co.RECHECK:
                        ui.label("re-check").classes("text-xs shrink-0") \
                            .style(f"color:{theme.STATUS_TEXT['high']}")

        def _card(res) -> None:
            item_id = state["selected"]
            if item_id is None:
                c.empty("Select a row to decide it.", icon="fact_check")
                return
            item = find(res, item_id)
            if isinstance(item, co.Lost):
                _lost_card(item)
            else:
                _row_card(item)

        def _quote(text: str) -> None:
            ui.label("Old comment").classes("sx-eyebrow mt-1")
            ui.label(text).classes("text-base px-3 py-2 rounded w-full") \
                .style(f"background:{theme.SURFACE_2};border-left:3px solid {theme.BRAND}")

        def _diff_table(p) -> None:
            named = {d.key for d in p.mentioned}
            ui.label("What changed").classes("sx-eyebrow mt-1")
            with ui.element("div").classes("w-full grid gap-x-4 gap-y-1 items-baseline") \
                    .style("grid-template-columns: minmax(7rem, max-content) 1fr 1fr"):
                for heading in ("Attribute", "Old report", "New report"):
                    ui.label(heading).classes("text-xs sx-faint")
                for d in p.diffs:
                    hit = d.key in named
                    ui.label(d.label + (" · in the comment" if hit else "")) \
                        .classes("text-sm") \
                        .style(f"color:{theme.STATUS_TEXT['high']}" if hit else "")
                    ui.label(d.old or "—").classes("text-sm sx-mono sx-muted")
                    ui.label(d.new or "—").classes("text-sm sx-mono font-semibold")

        def _row_card(p) -> None:
            with ui.row().classes("items-center gap-2 flex-wrap"):
                if p.attention == co.RECHECK:
                    c.chip("high", "Re-check")
                c.chip("info", co.KIND_LABEL[p.kind])
                if p.decided:
                    c.chip("ok", DONE_LABEL[p.decision])
            ui.label(f"{p.sheet} · pin {p.pin} · {_circuit(p)}") \
                .classes("text-base font-semibold sx-mono")
            for side in p.sides_gone:
                c.note("high", f"Side {side} is gone — the wire no longer mates on "
                               "that side.")
            if p.diffs:
                _diff_table(p)
            _quote(p.old_comment)
            named = sorted({co.label_of(d.key) for d in p.mentioned})
            if named:
                c.note("high", f"It talks about {', '.join(named)} — which changed. "
                               "Check it still holds before copying it.")
            elif p.diffs and not p.sides_gone:
                c.note("info", "It is about something this change does not touch.")
            if p.existing:
                c.note("info", f"The new report already says: “{p.existing}”.")
            for alt in p.alternatives:
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    ui.label(f"Another old comment matched this row equally well: "
                             f"“{alt}”").classes("text-sm sx-muted")
                    ui.button("Use that one",
                              on_click=lambda _e, t=alt: decide(p.id, co.NEW, t)) \
                        .props("flat dense no-caps")

            ui.separator().classes("my-1")
            options = [(co.COPY, "Copy old comment", "C"),
                       (co.NEW, "Write new comment", "W"),
                       (co.BLANK, "Leave blank", "B")]
            if p.existing:
                options.append((co.KEEP, "Keep new report's comment", "K"))
            emphasis = p.decision or p.suggested
            with ui.row().classes("gap-2 flex-wrap items-center"):
                for decision, label, key in options:
                    weight = "unelevated" if decision == emphasis else "outline"
                    if decision == co.NEW:
                        handler = lambda _e: start_writing(p.id)  # noqa: E731
                    else:
                        handler = lambda _e, d=decision: decide(p.id, d)  # noqa: E731
                    with ui.button(label, on_click=handler) \
                            .props(f'{weight} dense no-caps aria-keyshortcuts="{key}"'):
                        ui.label(key).classes("sx-kbd ml-2")
                if p.suggested and not p.decided:
                    ui.label(f"Suggested: {co.DECISION_LABEL[p.suggested].lower()}") \
                        .classes("sx-caption")
            if p.decided and p.result:
                c.note("ok", f"Will be written as: “{p.result}”")
            if state["writing"] == p.id:
                with ui.row().classes("w-full items-end gap-2 no-wrap"):
                    field = ui.input("New comment", value=p.text or p.old_comment) \
                        .props("dense autofocus").classes("grow")
                    field.on("keydown.enter", lambda _e: save_new(p.id, field.value))
                    field.on("keydown.escape", lambda _e: stop_writing())
                    ui.button("Save comment",
                              on_click=lambda _e: save_new(p.id, field.value)) \
                        .props("unelevated dense no-caps")
                    ui.button("Cancel", on_click=lambda _e: stop_writing()) \
                        .props("flat dense no-caps")

        def _lost_card(x) -> None:
            with ui.row().classes("items-center gap-2 flex-wrap"):
                c.chip("high", "No row in the new report")
                if x.decided:
                    c.chip("ok", DONE_LABEL[x.ack])
            ui.label(f"{x.sheet} · pin {x.pin} · {_circuit(x)}") \
                .classes("text-base font-semibold sx-mono")
            _quote(x.comment)
            c.note("info", f"It did not carry: {x.reason}.")
            ui.separator().classes("my-1")
            with ui.row().classes("gap-2 flex-wrap items-center"):
                for ack, key in ((co.REPLACE, "R"), (co.OBSOLETE, "X")):
                    weight = "unelevated" if x.ack == ack else "outline"
                    with ui.button(co.ACK_LABEL[ack],
                                   on_click=lambda _e, a=ack: acknowledge(x.id, a)) \
                            .props(f'{weight} dense no-caps aria-keyshortcuts="{key}"'):
                        ui.label(key).classes("sx-kbd ml-2")
            ui.label("Re-place it by hand puts the comment on the list under "
                     "Generate, so it is not forgotten.").classes("sx-caption")

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
                    missing = []
                    if res.undecided:
                        missing.append(f"a decision on {len(res.undecided)} row(s)")
                    if res.unacknowledged:
                        missing.append(f"an acknowledgement of {len(res.unacknowledged)} "
                                       "comment(s) with no row")
                    return missing

                c.action("Write the commented report", lambda: generate(),
                         needs=needs, icon="edit_note")
                res = state["result"]
                if state["output"]:
                    name, data = state["output"]
                    c.note("ok", f"{res.counts()['written']} comment(s) written into {name}.")
                    c.download(name, lambda d=data: d, dress=False)
                if res is not None:
                    by_hand = [x for x in res.lost if x.ack == co.REPLACE]
                    if by_hand:
                        c.note("high", f"{len(by_hand)} comment(s) to re-place by hand — "
                                       "nothing in the new report had their pin and "
                                       "circuit.")
                        c.frame_table([{"sheet": x.sheet, "pin": x.pin,
                                        "circuit": _circuit(x), "comment": x.comment}
                                       for x in by_hand],
                                      labels={"sheet": "Sheet", "pin": "Pin",
                                              "circuit": "Circuit",
                                              "comment": "Old comment"},
                                      pagination=10)

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
        state.update(result=result, output=None, selected=None, filter="open",
                     writing=None, history=[])
        refresh("review", "generate")

    async def generate() -> None:
        res = state["result"]
        if res is None or res.blocking:
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
