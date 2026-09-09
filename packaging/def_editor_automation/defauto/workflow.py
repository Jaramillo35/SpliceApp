"""The automation test: open a harness, open its circuits, filter for one.

Deliberately one sequence, not a toolkit. This is the thing you run first on
Windows to answer a single question — does driving DEF Editor through UI
Automation work at all? — and everything about it is shaped by that:

* it asks for four values and works the rest out,
* it reports every step separately, so a failure names the step that failed
  rather than leaving a traceback to be read backwards,
* it stops at the first failure, because step 7 tells you nothing once step 3
  did not happen.

The composite is not one of the four. DEF Editor's sequence runs program >
model year > phase > composite > harness, so a harness cannot be reached
without one; rather than asking for a value that is a detail of where the
harness lives, this searches the composites the filter returned and reports
which one it found the harness in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from defauto import ids
from defauto.backend import Grid

#: The circuit the test filters for. One constant, one place to change it.
TARGET_CIRCUIT = "B4"


@dataclass
class Step:
    name: str
    ok: Optional[bool] = None      # None = not run yet
    detail: str = ""

    @property
    def mark(self) -> str:
        return {True: "PASS", False: "FAIL", None: "...."}[self.ok]


def plan(program: str, year: str, phase: str, harness: str,
         target: str = TARGET_CIRCUIT) -> List[Step]:
    """The steps this test will run, before any of them have."""
    return [Step("Attach and check the controls are present"),
            Step(f"Select program {program}"),
            Step(f"Select model year {year}"),
            Step(f"Select phase {phase}"),
            Step("Press Filter and read the composites"),
            Step(f"Find the composite holding {harness}"),
            Step(f"Select harness {harness}"),
            Step("Open the harness page"),
            Step("Open the Circuits page"),
            Step(f"Filter circuits for {target}")]


@dataclass
class Outcome:
    steps: List[Step] = field(default_factory=list)
    grid: Grid = field(default_factory=Grid)
    composite: str = ""
    #: the harness as DEF Editor spells it, which may differ in case from
    #: what was typed
    harness: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)

    @property
    def failed(self) -> Optional[Step]:
        return next((s for s in self.steps if s.ok is False), None)


def run(session, program: str, year: str, phase: str, harness: str,
        target: str = TARGET_CIRCUIT,
        on_step: Optional[Callable[[Step], None]] = None) -> Outcome:
    """Run the whole test, reporting each step as it finishes."""
    steps = plan(program, year, phase, harness, target)
    outcome = Outcome(steps=steps)
    index = 0

    def done(ok: bool, detail: str = "") -> None:
        steps[index].ok, steps[index].detail = ok, detail
        if on_step is not None:
            on_step(steps[index])

    try:
        # 1 - the controls this test depends on
        missing = [a for a, found in session.diagnose() if not found]
        if missing:
            done(False, f"missing: {', '.join(missing)} — edit defauto/ids.py")
            return outcome
        done(True, "all essential AutomationIds found")
        index += 1

        # 2, 3, 4 - the cascade, one combo at a time so a wrong value is
        # reported against the combo that refused it
        for auto_id, value in ((ids.COMBO_VEHICLE_LINE, program),
                               (ids.COMBO_MODEL_YEAR, year),
                               (ids.COMBO_PHASE, phase)):
            offered = session.backend.options(auto_id)
            if value not in offered:
                done(False, f"not offered. Available: {', '.join(offered) or '(none)'}")
                return outcome
            session.backend.select(auto_id, value)
            done(True, f"selected from {len(offered)} option(s)")
            index += 1

        session.composite.selection.vehicle_line = program
        session.composite.selection.model_year = year
        session.composite.selection.phase = phase

        # 5 - Filter is what fills the grid; without it there is nothing to search
        grid = session.composite.search()
        if not len(grid):
            done(False, "Filter returned no composites for this programme")
            return outcome
        done(True, f"{len(grid)} composite(s)")
        index += 1

        # 6 - which composite holds the harness, and how DEF Editor spells it
        found = _locate(session, harness)
        if found is None:
            done(False, f"{harness!r} is not in any of the "
                        f"{len(session.composite.composites())} composite(s)")
            return outcome
        outcome.composite, actual = found
        outcome.harness = actual
        done(True, f"in {outcome.composite}"
                   + ("" if actual == harness else f", spelled {actual!r}"))
        index += 1

        # 7 - select the application's spelling, never the typed one: the
        # list box matches exactly, so "body_left" would be refused here even
        # though step 6 found it
        session.composite.choose_harness(actual)
        done(True, str(session.composite.selection))
        index += 1

        # 8
        control = session.harness.open()
        done(True, f"on {control}")
        index += 1

        # 9
        control = session.circuits.open()
        total = len(session.circuits.read())
        done(True, f"on {control} — {total} circuit(s) before filtering")
        index += 1

        # 10 - the point of the whole exercise
        session.circuits.clear_filters()
        outcome.grid = session.circuits.read(target)
        if not len(outcome.grid):
            done(False, f"no circuit matching {target!r} on this harness")
            return outcome
        # Whether DEF Editor's circuit filter matches the Circuit column or
        # anywhere in the row is not something this kit can know without
        # standing in front of it — a sales code of ZB4 contains B4. Both
        # numbers are reported so the run says which it turned out to be.
        exact = _exact(outcome.grid, target)
        detail = f"{len(outcome.grid)} row(s) matching {target!r}"
        if exact != len(outcome.grid):
            detail += (f" — {exact} with Circuit exactly {target!r}; the rest "
                       "matched elsewhere in the row")
        done(True, detail)
    except Exception as exc:  # noqa: BLE001 - the step is the diagnosis
        steps[index].ok = False
        steps[index].detail = f"{type(exc).__name__}: {exc}"
        if on_step is not None:
            on_step(steps[index])
    return outcome


def _exact(grid: Grid, target: str) -> int:
    """Rows whose Circuit column IS the target, not merely contains it."""
    try:
        return sum(1 for value in grid.column("Circuit")
                   if value.strip().lower() == target.strip().lower())
    except KeyError:
        return len(grid)


def _locate(session, harness: str) -> Optional[Tuple[str, str]]:
    """``(composite, harness as the application spells it)``, or None.

    Matched case-insensitively, because an engineer typing a harness name
    should not have to match the application's capitalisation — but the
    application's own spelling is returned, because the list box that follows
    matches exactly and would refuse the typed one.
    """
    wanted = harness.strip().lower()
    for composite in session.composite.composites():
        session.composite.choose_composite(composite)
        for name in session.composite.harnesses():
            if name.strip().lower() == wanted:
                return composite, name
    return None
