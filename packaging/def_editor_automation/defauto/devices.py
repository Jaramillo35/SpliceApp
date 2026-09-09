"""The Devices module: one grid, filtered and read."""

from __future__ import annotations

from typing import Optional

from defauto import gridreader, ids
from defauto.backend import Backend, Grid
from defauto.navigation import Navigation


class Devices:
    GRID = ids.GRID_DEVICES
    FILTER = ids.TEXT_FILTER
    SCOPE = ids.UC_DEVICES

    def __init__(self, backend: Backend, navigation: Navigation) -> None:
        self.backend = backend
        self.navigation = navigation

    def open(self) -> str:
        return self.navigation.devices()

    def read(self, needle: str = "") -> Grid:
        if needle:
            self.backend.set_text(self.FILTER, needle)
        return self.backend.grid(self.GRID)

    def find(self, cnum: str) -> Optional[dict]:
        return gridreader.find(self.read(), "CNUM", cnum)
