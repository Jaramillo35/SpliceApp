"""The Circuits module.

The only module with filters beyond a text box: two checkboxes narrow the
grid to circuits that are missing or single-ended, and Live Checks makes the
application validate as it goes. They are set through the same AutomationIds
an engineer clicks, so the automation and the screen never disagree about
which rows are in view.
"""

from __future__ import annotations

from typing import List, Optional

from defauto import gridreader, ids
from defauto.backend import Backend, Grid
from defauto.navigation import Navigation


class Circuits:
    GRID = ids.GRID_CIRCUITS
    FILTER = ids.TEXT_FILTER_CIRCUIT
    SCOPE = ids.UC_CIRCUITS

    def __init__(self, backend: Backend, navigation: Navigation) -> None:
        self.backend = backend
        self.navigation = navigation

    def open(self) -> str:
        return self.navigation.circuits()

    def live_checks(self, on: bool = True) -> None:
        self.backend.set_checked(ids.CHECK_LIVE_CHECKS, on)

    def only_missing(self, on: bool = True) -> None:
        self.backend.set_checked(ids.CHECK_CKT_MISSING, on)

    def only_single_ended(self, on: bool = True) -> None:
        self.backend.set_checked(ids.CHECK_CKT_SINGLE_END, on)

    def clear_filters(self) -> None:
        self.backend.set_text(self.FILTER, "")
        self.only_missing(False)
        self.only_single_ended(False)

    def connectors(self) -> List[str]:
        return self.backend.options(ids.COMBO_DELPHI_CONNECTOR)

    def by_connector(self, connector: str) -> Grid:
        self.backend.select(ids.COMBO_DELPHI_CONNECTOR, connector)
        return self.backend.grid(self.GRID)

    def read(self, needle: str = "") -> Grid:
        if needle:
            self.backend.set_text(self.FILTER, needle)
        return self.backend.grid(self.GRID)

    def find(self, circuit: str) -> Optional[dict]:
        return gridreader.find(self.read(), "Circuit", circuit)

    def missing(self) -> Grid:
        """Circuits the application flags as missing — a defect list, not a view."""
        self.clear_filters()
        self.only_missing(True)
        return self.backend.grid(self.GRID)

    def single_ended(self) -> Grid:
        self.clear_filters()
        self.only_single_ended(True)
        return self.backend.grid(self.GRID)
