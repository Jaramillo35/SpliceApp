"""Card 1 — the two upload rows, the gated Load button, the progress bar,
and what the load had to say (restored mappings, carried repairs, files
that could not be read) — as notes under the action, not a stack of toasts."""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app.pages.circuit_applicability import actions
from nicegui_app.pages.circuit_applicability.workbench import Workbench


def _restored(stored: dict) -> str:
    """What the store is holding, in the engineer's words."""
    counts = [(len(stored.get("mapping", {})), "family mapping(s)"),
              (len(stored.get("fixes", {})), "sales-code repair(s)"),
              (len(stored.get("cleanup", {})), "cleanup selection(s)")]
    return ", ".join(f"{n} {label}" for n, label in counts if n)


def build(wb: Workbench) -> None:
    state = wb.state

    def missing() -> list[str]:
        out = []
        if not state["dtx"]:
            out.append("the DTx report")
        if not state["uploads"]:
            out.append("at least one complexity file")
        return out

    with c.section("1 · Inputs",
                   "Programme and phase are read from inside both file types "
                   "— the DTx title block and each complexity file's Harness "
                   "PN sheet — never from the filenames.", step="Inputs"):
        with ui.row().classes("w-full gap-4 flex-wrap"):
            c.upload_row("Detailed DTx Circuits Report",
                         lambda n, b: state.update(dtx=(n, b)),
                         accept=".xls,.xlsx,.xlsm")
            c.upload_row("Individual harness complexity file(s)",
                         lambda n, b: state["uploads"].__setitem__(n, b),
                         accept=".xlsm,.xlsx", multiple=True)
        c.action("Load and match", lambda: actions.load(wb), needs=missing)
        wb.progress = ui.column().classes("w-full gap-1")

        @ui.refreshable
        def notes_view() -> None:
            # Reopening the page from the Overview's Continue list used to
            # look like nothing had been kept: the uploads are per-session
            # bytes, while the mapping, the repairs and the ticks are on
            # disk. Say so before a file is loaded, so "continue" is true.
            if not state["rows"]:
                waiting = _restored(state["stored"])
                if waiting:
                    c.note("info", "Saved from your last session: " + waiting
                           + ". Load the same DTx and complexity files and it "
                             "is applied again.")
            for kind, text in state["load_notes"]:
                c.note(kind, text)

        wb.views["load_notes"] = notes_view
        notes_view()
