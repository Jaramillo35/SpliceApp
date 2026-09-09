"""Steps 1 and 2: pick a programme, then pick a harness out of a composite.

Every workflow starts here, and the ordering is not decoration. The three
combo boxes cascade — a model year the chosen vehicle line does not build is
not offered — and the composite grid stays empty until Filter is pressed. A
workflow that skips Filter reads an empty grid and reports "no composites"
rather than failing, which is the kind of quiet wrong answer this layer
exists to make impossible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from defauto import ids
from defauto.backend import AutomationError, Backend, Grid


@dataclass
class Selection:
    vehicle_line: Optional[str] = None
    model_year: Optional[str] = None
    phase: Optional[str] = None
    composite: Optional[str] = None
    harness: Optional[str] = None

    @property
    def complete(self) -> bool:
        return all((self.vehicle_line, self.model_year, self.phase,
                    self.composite, self.harness))

    def __str__(self) -> str:
        parts = [self.vehicle_line, self.model_year, self.phase,
                 self.composite, self.harness]
        return " / ".join(p for p in parts if p) or "(nothing selected)"


class Composite:
    def __init__(self, backend: Backend) -> None:
        self.backend = backend
        self.selection = Selection()

    # ------------------------------------------------------------ step 1
    def vehicle_lines(self) -> List[str]:
        return self.backend.options(ids.COMBO_VEHICLE_LINE)

    def model_years(self) -> List[str]:
        return self.backend.options(ids.COMBO_MODEL_YEAR)

    def phases(self) -> List[str]:
        return self.backend.options(ids.COMBO_PHASE)

    def choose_programme(self, vehicle_line: str, model_year: str,
                         phase: str) -> Selection:
        """Set all three combos, in the order the form cascades them."""
        self.backend.select(ids.COMBO_VEHICLE_LINE, vehicle_line)
        self.backend.select(ids.COMBO_MODEL_YEAR, model_year)
        self.backend.select(ids.COMBO_PHASE, phase)
        self.selection = Selection(vehicle_line, model_year, phase)
        return self.selection

    def search(self) -> Grid:
        """Press Filter and read the composite grid.

        Returning the grid rather than a bare success flag is the point: the
        caller sees what came back, and an empty result is visible instead of
        assumed.
        """
        self.backend.click(ids.BUTTON_FILTER)
        return self.backend.grid(ids.GRID_COMPOSITE)

    def composites(self) -> List[str]:
        return self.backend.options(ids.LIST_COMPOSITE)

    # ------------------------------------------------------------ step 2
    def choose_composite(self, name: str) -> Selection:
        self.backend.select(ids.LIST_COMPOSITE, name)
        self.selection.composite, self.selection.harness = name, None
        return self.selection

    def harnesses(self, needle: str = "") -> List[str]:
        """The harnesses of the chosen composite, optionally filtered."""
        if needle:
            self.backend.set_text(ids.TEXT_FILTER, needle)
        found = self.backend.options(ids.LIST_HARNESS)
        if needle:
            low = needle.lower()
            found = [h for h in found if low in h.lower()]
        return found

    def choose_harness(self, name: str) -> Selection:
        self.backend.select(ids.LIST_HARNESS, name)
        self.selection.harness = name
        return self.selection

    # --------------------------------------------------------- all of it
    def open(self, vehicle_line: str, model_year: str, phase: str,
             composite: str, harness: str) -> Selection:
        """The whole of steps 1 and 2, which is how callers actually use it."""
        self.choose_programme(vehicle_line, model_year, phase)
        grid = self.search()
        if not len(grid):
            raise AutomationError(
                f"No composites for {vehicle_line} / {model_year} / {phase}")
        self.choose_composite(composite)
        self.choose_harness(harness)
        return self.selection
