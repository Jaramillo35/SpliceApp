"""The Navigation layer: move between DEF Editor's pages, and nothing else.

Kept separate because every other module needs it and none of them should
know how it works. Menu items are used in preference to clicking around the
form, per the automation rules, and each page is named by the user control it
lands on so a caller can assert where it ended up.
"""

from __future__ import annotations

from typing import Tuple

from defauto import ids
from defauto.backend import Backend

#: menu path -> the user control that page is built from
PAGES = {
    (ids.MENU_HARNESS,): ids.UC_HARNESS_EDIT,
    (ids.MENU_DEVICES,): ids.UC_DEVICES,
    (ids.MENU_CIRCUITS,): ids.UC_CIRCUITS,
    (ids.MENU_SPLICES,): ids.UC_SPLICES,
    (ids.MENU_COMPLEXITY, "Devices"): ids.UC_DEVICES,
    (ids.MENU_COMPLEXITY, "Circuits"): ids.UC_CIRCUITS_USAGE,
    (ids.MENU_COMPLEXITY, "Sales Codes"): ids.UC_SALES_CODES,
    (ids.MENU_QUALITY_CHECKS, "Circuits"): ids.UC_CHECKS_CONNECTORS,
    (ids.MENU_QUALITY_CHECKS, "Inlines"): ids.UC_CHECKS_INLINE,
}


class Navigation:
    def __init__(self, backend: Backend) -> None:
        self.backend = backend
        self.here: Tuple[str, ...] = ()

    def go(self, *path: str) -> str:
        """Open a page and return the user control it is built from."""
        if tuple(path) not in PAGES:
            raise KeyError(f"{' -> '.join(path)} is not a known page; "
                           f"known: {sorted(' -> '.join(p) for p in PAGES)}")
        self.backend.menu(*path)
        self.here = tuple(path)
        return PAGES[tuple(path)]

    # convenience, so callers read as the menu bar reads
    def harness(self) -> str:
        return self.go(ids.MENU_HARNESS)

    def devices(self) -> str:
        return self.go(ids.MENU_DEVICES)

    def circuits(self) -> str:
        return self.go(ids.MENU_CIRCUITS)

    def splices(self) -> str:
        return self.go(ids.MENU_SPLICES)

    def complexity_devices(self) -> str:
        return self.go(ids.MENU_COMPLEXITY, "Devices")

    def complexity_circuits(self) -> str:
        return self.go(ids.MENU_COMPLEXITY, "Circuits")

    def complexity_sales_codes(self) -> str:
        return self.go(ids.MENU_COMPLEXITY, "Sales Codes")

    def checks_circuits(self) -> str:
        return self.go(ids.MENU_QUALITY_CHECKS, "Circuits")

    def checks_inlines(self) -> str:
        return self.go(ids.MENU_QUALITY_CHECKS, "Inlines")
