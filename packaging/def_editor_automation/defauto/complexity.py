"""The Complexity module: devices, circuits and sales codes.

Three pages that answer one question between them — which harness part
numbers carry what — so they are one class with three readers rather than
three classes that would each have to be navigated to separately.
"""

from __future__ import annotations

from typing import Dict, List

from defauto import ids
from defauto.backend import Backend, Grid
from defauto.navigation import Navigation


class Complexity:
    def __init__(self, backend: Backend, navigation: Navigation) -> None:
        self.backend = backend
        self.navigation = navigation

    # ---------------------------------------------------------- devices
    def devices(self, needle: str = "") -> Grid:
        self.navigation.complexity_devices()
        if needle:
            self.backend.set_text(ids.TEXT_FILTER, needle)
        return self.backend.grid(ids.GRID_DEVICE_COMPLEXITY)

    # --------------------------------------------------------- circuits
    def circuits(self, circuit: str = "", sales_code: str = "") -> Grid:
        """Circuit usage, narrowed by circuit and/or by sales code.

        Two separate filter boxes on the same page, which is exactly the sort
        of thing that gets crossed over when ids are guessed rather than
        looked up — hence both being named in ``ids.py``.
        """
        self.navigation.complexity_circuits()
        if circuit:
            self.backend.set_text(ids.TEXT_FILTER_CIRCUIT_COMPLEXITY, circuit)
        if sales_code:
            self.backend.set_text(ids.TEXT_FILTER_SALES_CODE, sales_code)
        return self.backend.grid(ids.GRID_CIRCUIT_COMPLEXITY)

    # ------------------------------------------------------ sales codes
    def sales_codes(self, harness_pn: str = "") -> Grid:
        self.navigation.complexity_sales_codes()
        if harness_pn:
            self.backend.set_text(ids.TEXT_FILTER_HARNESS_PN, harness_pn)
        return self.backend.grid(ids.GRID_SALES_CODES_EDIT)

    def available_codes(self) -> Grid:
        self.navigation.complexity_sales_codes()
        return self.backend.grid(ids.GRID_SALES_CODES_AVAILABLE)

    def used_codes(self) -> Grid:
        self.navigation.complexity_sales_codes()
        return self.backend.grid(ids.GRID_SALES_CODES_USED)

    def compare_codes(self) -> Dict[str, List[str]]:
        """Available against used — the comparison the page invites but does not make.

        Returned as three lists rather than a verdict: which side of the
        difference matters is an engineering judgement, not this layer's.
        """
        available = set(self.available_codes().column("Sales Code"))
        used = set(self.used_codes().column("Sales Code"))
        return {
            "available_only": sorted(available - used),
            "used_only": sorted(used - available),
            "both": sorted(available & used),
        }
