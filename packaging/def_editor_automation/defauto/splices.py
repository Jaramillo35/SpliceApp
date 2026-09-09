"""The Splices module: the splice list, and the circuit-family lookup beside it."""

from __future__ import annotations

from typing import List, Optional

from defauto import gridreader, ids
from defauto.backend import Backend, Grid
from defauto.navigation import Navigation


class Splices:
    GRID = ids.GRID_SPLICES
    FILTER = ids.TEXT_FILTER_SPLICE
    SCOPE = ids.UC_SPLICES

    def __init__(self, backend: Backend, navigation: Navigation) -> None:
        self.backend = backend
        self.navigation = navigation

    def open(self) -> str:
        return self.navigation.splices()

    def read(self, needle: str = "") -> Grid:
        if needle:
            self.backend.set_text(self.FILTER, needle)
        return self.backend.grid(self.GRID)

    def find(self, splice_number: str) -> Optional[dict]:
        return gridreader.find(self.read(), "Splice", splice_number)

    def circuit_families(self) -> List[str]:
        return self.backend.options(ids.LIST_CIRCUIT_FAMILY)

    def by_circuit_family(self, family: str) -> Grid:
        self.backend.select(ids.LIST_CIRCUIT_FAMILY, family)
        return self.backend.grid(self.GRID)

    def cavity_count(self) -> str:
        return self.backend.text(ids.TEXT_CREATE_CAV_COUNT)
