"""Card 3 — connect each DTx family to its complexity file(s)."""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme
from nicegui_app.pages.circuit_applicability import actions
from nicegui_app.pages.circuit_applicability.common import GREEN, GRID, ROW_H, line
from nicegui_app.pages.circuit_applicability.workbench import Workbench


def build(wb: Workbench) -> None:
    state = wb.state

    @ui.refreshable
    def mapping_view() -> None:
        if not state["families"]:
            return
        from splice.dtxcircuits import matching

        meta = state["dtx_meta"]
        mapped = state["mapping"]
        labels = wb.labels()
        suggestions = matching.suggest(
            [f for f, _n in state["families"]], labels)
        orphans = matching.orphans(labels, suggestions)
        connected = sum(1 for v in mapped.values() if v)

        with c.card("3 · Map families to complexity files",
                    f"DTx {meta.program or '?'} · phase {meta.phase or '?'} "
                    f"· {len(state['families'])} families · "
                    f"{len(state['harnesses'])} file(s). A family may take "
                    f"several harnesses."):
            with ui.row().classes("gap-2 flex-wrap items-center"):
                c.chip("ok", f"{connected} connected")
                if len(state["families"]) - connected:
                    c.chip("blocker",
                           f"{len(state['families']) - connected} open")
                if orphans:
                    c.chip("review", f"{len(orphans)} with no likely family")
                for f in (state["corr"].blocking if state["corr"] else []):
                    c.chip("blocker", f"{f.filename}: {f.detail}")
                ui.checkbox("Only unconnected", value=state["only_open"],
                            on_change=lambda e: (
                                state.update(only_open=e.value),
                                mapping_view.refresh())) \
                    .props("dense").classes("text-xs")

            rows = [(f, n) for f, n in state["families"]
                    if not (state["only_open"] and mapped.get(f))]
            if not rows:
                c.chip("ok", "Every family is connected")

            with ui.element("div").classes("w-full grid gap-x-2 gap-y-1") \
                    .style(GRID):
                for title in ("DTx harness family", "",
                              "Harness complexity file(s)",
                              "Suggested — click to add"):
                    ui.label(title).classes(
                        "sx-eyebrow")
                for family, n_rows in rows:
                    chosen = mapped.get(family, [])
                    _family_cell(family, n_rows, len(chosen))
                    ui.html(line(bool(chosen)))
                    _select_cell(family, chosen, suggestions, orphans, labels)
                    _candidates_cell(family, suggestions.get(family, []),
                                     chosen)

            with ui.row().classes("items-center gap-3 mt-2"):
                ui.button("Run analysis", icon="play_arrow",
                          on_click=lambda: actions.run(wb)).props("unelevated dense") \
                    .set_enabled(any(mapped.values()))
                ui.label("Only connected families are analyzed; each "
                         "family × harness pairing is resolved separately.") \
                    .classes("text-xs sx-muted")
                if wb.open_issues():
                    c.chip("blocker",
                           f"{len(wb.open_issues())} sales-code expression(s) "
                           "still malformed — their circuits will read as "
                           "never built")

    def _family_cell(family: str, n_rows: int, n_mapped: int) -> None:
        with ui.element("div").classes(
                "rounded px-2 flex items-center justify-between gap-1") \
                .style(f"min-height:{ROW_H}px;background:{theme.SURFACE_2};"
                       f"border:1px solid {theme.LINE}"):
            ui.label(family).classes("text-xs font-semibold truncate")
            text = str(n_rows) if n_mapped < 2 else f"{n_rows} · ×{n_mapped}"
            ui.label(text).classes("text-xs sx-muted shrink-0")

    def _select_cell(family: str, chosen: list, suggestions, orphans: set,
                     labels: dict) -> None:
        """Multi-select of complexity files, with the picks shown as
        removable chips beneath it."""
        with ui.element("div").classes("flex flex-col justify-center gap-1") \
                .style(f"min-height:{ROW_H}px"):
            from splice.dtxcircuits import matching
            select = ui.select(
                dict(matching.rank_options(family, labels, suggestions,
                                           orphans)),
                value=list(chosen), multiple=True,
                label=None if chosen else "add harness…",
            ).props("dense outlined use-chips=false options-dense") \
                .classes("w-full text-xs")
            select.on_value_change(
                lambda e, fam=family: _set_mapping(fam, e.value))
            if chosen:
                with ui.row().classes("gap-1 flex-wrap"):
                    for filename in chosen:
                        _mapped_chip(family, filename, labels)

    def _mapped_chip(family: str, filename: str, labels: dict) -> None:
        harness = state["harnesses"].get(filename)
        detail = (f"def {harness.def_id} · {len(harness.builds)}b · "
                  f"{len(harness.complexity_codes)}c" if harness else "")
        with ui.row().classes(
                "items-center gap-1 rounded px-2 py-0.5 shrink-0") \
                .style(f"background:{GREEN}1f;border:1px solid {GREEN}66"):
            ui.label(labels.get(filename, filename)) \
                .classes("text-xs font-semibold").style(f"color:{GREEN}")
            if detail:
                ui.label(detail).classes("text-xs sx-muted")
            ui.button(icon="close",
                      on_click=lambda f=family, n=filename: _remove(f, n)) \
                .props("flat dense round size=xs")

    def _candidates_cell(family: str, suggestions, chosen: list) -> None:
        with ui.element("div").classes("flex items-center gap-1 flex-wrap") \
                .style(f"min-height:{ROW_H}px"):
            available = [s for s in suggestions if s.key not in chosen]
            if not available:
                ui.label("—" if chosen else "no candidate") \
                    .classes("text-xs sx-muted")
                return
            for s in available:
                _chip(s.key, s.label, s.score, family=family,
                      tooltip=s.reason)

    def _chip(filename: str, label: str, sscore, *, family: str,
              tooltip: str = "") -> None:
        """A suggestion. Clicking adds it to that family's mapping."""
        strong = sscore is not None and sscore >= 0.7
        colour = GREEN if strong else theme.STATUS["review"]
        chip = ui.element("div").classes(
            "rounded px-2 py-0.5 cursor-pointer shrink-0 truncate") \
            .style(f"background:{colour}1f;border:1px solid {colour}66;"
                   f"max-width:12rem")
        with chip:
            text = label if sscore is None else f"{label}  {sscore:.0%}"
            ui.label(text).classes("text-xs font-semibold truncate") \
                .style(f"color:{colour}")
            if tooltip:
                ui.tooltip(tooltip)
        chip.on("click", lambda _e, f=filename, fam=family: _add(fam, f))

    def _set_mapping(family: str, values) -> None:
        # de-duplicate while preserving the order the SE picked
        state["mapping"][family] = list(dict.fromkeys(values or []))
        wb.invalidate()

    def _add(family: str, filename: str) -> None:
        from splice.dtxcircuits import matching
        matching.add_mapping(state["mapping"], family, filename)
        wb.invalidate()

    def _remove(family: str, filename: str) -> None:
        from splice.dtxcircuits import matching
        matching.remove_mapping(state["mapping"], family, filename)
        wb.invalidate()

    wb.views["mapping"] = mapping_view
    mapping_view()
