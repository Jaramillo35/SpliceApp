"""The state every card shares, and the views they refresh in each other.

The page used to be one 1,100-line function: six cards as nested closures
over one ``state`` dict, each calling the others' ``.refresh()`` by name.
That worked, and nobody could navigate it. The closures are now modules,
and what they shared lives here — the dict, unchanged, plus a registry of
the refreshable views so a card can still say "the chart is stale" without
importing the chart.
"""

from __future__ import annotations

from typing import Callable, Dict

from nicegui import ui

from splice.dtxcircuits import quality as quality_mod
from splice.dtxcircuits import store


class Workbench:
    def __init__(self) -> None:
        self.state: dict = {
            "dtx": None, "uploads": {},
            "rows": [], "dtx_meta": None, "families": [],
            "harnesses": {},        # filename -> Harness
            "metas": {},            # filename -> ComplexityMeta
            "mapping": {},          # family -> [filename, ...] (a family may take
                                    #            several harnesses)
            "corr": None, "entries": [], "selected": None, "only_open": False,
            #: rows ticked for the Complexity Cleanup Notes column, by item key
            "cleanup": {},
            "filters": {"findings": False, "needs_review": False,
                        "verdicts": set(), "condition": None},
            #: which review tab is open, so a refresh does not snap back
            "tab": "circuits",
            #: measured on load and again after analysis
            "quality": None,
            #: one circuit chart per family x harness, built with the analysis
            "charts": [],
            #: which chart is expanded, so a refresh does not collapse it
            "chart_open": None,
            #: keys the SE explicitly unticked — never auto-selected again
            "dismissed": set(),
            #: malformed sales-code expressions, and the repairs confirmed for them
            "issues": [], "fixes": {},
            "issue_filter": {"unresolved_only": True, "kinds": set()},
            #: what the previous session left behind
            "stored": store.load(),
        }
        self.state["cleanup"] = store.restore_cleanup(self.state["stored"].get("cleanup", {}))
        self.state["fixes"] = dict(self.state["stored"].get("fixes", {}))
        self.state["dismissed"] = set(self.state["stored"].get("dismissed", []))

        #: the refreshable view of each card, by name, once the card is built
        self.views: Dict[str, Callable] = {}
        #: the progress container under the Load button; load/run draw into it
        self.progress = None

    # ------------------------------------------------------------ views
    def refresh(self, *names: str) -> None:
        """Re-render the named cards. Strict on purpose: a name that is not
        registered is a wiring mistake, not something to skip quietly."""
        for name in names:
            self.views[name].refresh()

    # ------------------------------------------------------- shared facts
    def identity_of(self) -> dict:
        """filename -> the identity the mapping is stored under."""
        state = self.state
        return {f: store.harness_identity(
                    state["harnesses"][f].def_id,
                    state["metas"][f].harness or state["harnesses"][f].name)
                for f in state["harnesses"]}

    def labels(self) -> dict:
        state = self.state
        return {f: (state["metas"][f].harness or state["harnesses"][f].name)
                for f in state["harnesses"]}

    def open_issues(self) -> list:
        return [i for i in self.state["issues"]
                if i.expression not in self.state["fixes"]]

    # ------------------------------------------------------- shared moves
    def persist(self) -> None:
        """Keep the mapping and the cleanup ticks for next time."""
        state = self.state
        try:
            store.save({
                "mapping": store.remember_mapping(state["mapping"],
                                                  self.identity_of()),
                "cleanup": store.remember_cleanup(state["cleanup"]),
                "fixes": dict(state["fixes"]),
                "dismissed": sorted(state["dismissed"]),
            })
        except Exception as exc:  # noqa: BLE001 — never block the workbench
            ui.notify(f"Could not save the workbench: {exc}", type="warning")

    def measure(self) -> None:
        """Re-measure the DTx, but only once there is an analysis to
        measure against. Before that the never-built and coverage numbers
        would all read zero — a clean bill of health the run has not
        earned, and the worst thing to put in front of a customer."""
        state = self.state
        if not state["rows"] or state["dtx_meta"] is None \
                or not state["entries"]:
            state["quality"] = None
        else:
            state["quality"] = quality_mod.assess(
                state["rows"], state["dtx_meta"], state["issues"],
                state["entries"], state["fixes"])
        self.refresh("quality")

    def invalidate(self) -> None:
        """A mapping change makes any existing analysis stale."""
        self.state["entries"] = self.state["charts"] = []
        self.persist()
        self.measure()
        self.refresh("chart", "mapping", "results")
