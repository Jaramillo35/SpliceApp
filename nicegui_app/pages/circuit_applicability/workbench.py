"""The state every card shares, and the views they refresh in each other.

The page used to be one 1,100-line function: six cards as nested closures
over one ``state`` dict, each calling the others' ``.refresh()`` by name.
The closures are now modules, and what they shared lives here — the dict,
plus a registry of the refreshable views so a card can still say "the
chart is stale" without importing the chart.

Archetype B (workbench): the step bar and the KPI strip are derived from
the same state after every refresh, and every save carries the engineer's
name and a revision so two people on the shared server cannot overwrite
each other unnoticed.
"""

from __future__ import annotations

from typing import Callable, Dict

from nicegui import ui

from nicegui_app import components as c
from splice.dtxcircuits import quality as quality_mod
from splice.dtxcircuits import store

STEPS = ("Inputs", "Integrity", "Map", "Review", "Quality", "Chart")


class Workbench:
    def __init__(self) -> None:
        stored = store.load()
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
            "stored": stored,
            #: what the last load and run had to say (notes, not toasts)
            "load_notes": [], "auto_added": 0,
            #: the store's envelope as we last saw it
            "revision": stored.get("revision", 0),
            "saved_by": stored.get("saved_by", ""),
            "saved_at": stored.get("saved", ""),
        }
        self.state["cleanup"] = store.restore_cleanup(stored.get("cleanup", {}))
        self.state["fixes"] = dict(stored.get("fixes", {}))
        self.state["dismissed"] = set(stored.get("dismissed", []))

        #: the refreshable view of each card, by name, once the card is built
        self.views: Dict[str, Callable] = {}
        #: the progress container under the Load button; load/run draw into it
        self.progress = None
        #: the header label that says who saved last
        self.envelope: ui.label | None = None

    # ------------------------------------------------------------ views
    def refresh(self, *names: str) -> None:
        """Re-render the named cards, then the step bar and the KPI strip,
        which are derived from the same state. Strict on purpose: a name
        that is not registered is a wiring mistake, not something to skip."""
        for name in names:
            self.views[name].refresh()
        self.sync()

    def sync(self) -> None:
        """Step states and KPIs follow the state; nothing sets them by hand."""
        s = self.state
        open_issues = len(self.open_issues())
        fixed = sum(1 for i in s["issues"] if i.expression in s["fixes"])
        total = len(s["families"])
        connected = sum(1 for v in s["mapping"].values() if v)
        q = s["quality"]
        if not s["rows"]:
            states = {"Inputs": ("current", ""), "Integrity": ("waiting", ""),
                      "Map": ("waiting", ""), "Review": ("waiting", ""),
                      "Quality": ("waiting", ""), "Chart": ("waiting", "")}
        else:
            states = {
                "Inputs": ("done", f"{total} families · {len(s['harnesses'])} files"),
                "Integrity": (("blocked", f"{open_issues} unresolved") if open_issues
                              else ("done", f"{fixed} repaired" if fixed else "clean")),
                "Map": (("done", f"{connected} / {total}") if s["entries"]
                        else ("current", f"{connected} / {total}")),
                "Review": (("current", f"{len(s['cleanup'])} selected") if s["entries"]
                           else ("waiting", "")),
                "Quality": (("done", f"{q.finding_total} findings") if q is not None
                            else ("waiting", "")),
                "Chart": (("done", f"{len(s['charts'])} charts") if s["charts"]
                          else ("waiting", "")),
            }
        for name, (state, note) in states.items():
            c.set_step(name, state, note)
        if "kpis" in self.views:
            self.views["kpis"].refresh()
        self.show_envelope()

    def show_envelope(self) -> None:
        if self.envelope is None:
            return
        s = self.state
        if not s["saved_at"]:
            self.envelope.set_text("Nothing saved yet")
        else:
            by = s["saved_by"] or "unknown"
            self.envelope.set_text(f"Saved by {by} · {s['saved_at'][:16]} · rev {s['revision']}")

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
        """Keep the mapping and the cleanup ticks for next time, under the
        engineer's name. A save against a revision someone else has moved
        past is refused and said so — never merged silently."""
        state = self.state
        payload = {
            "mapping": store.remember_mapping(state["mapping"], self.identity_of()),
            "cleanup": store.remember_cleanup(state["cleanup"]),
            "fixes": dict(state["fixes"]),
            "dismissed": sorted(state["dismissed"]),
        }
        try:
            path = store.save(payload, by=c.who(),
                              expected_revision=state["revision"])
        except store.StaleWrite as other:
            ui.notify(f"Not saved — this workbench was changed by "
                      f"{other.by or 'someone else'} at {other.at}. Reload the "
                      "page to pick up their version before continuing.",
                      type="negative", multi_line=True, close_button=True)
            return
        except Exception as exc:  # noqa: BLE001 — never block the workbench
            ui.notify(f"Could not save the workbench: {exc}", type="warning")
            return
        env = store.envelope(store.load(path))
        state.update(revision=env["revision"], saved_by=env["by"], saved_at=env["at"])
        self.show_envelope()

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
