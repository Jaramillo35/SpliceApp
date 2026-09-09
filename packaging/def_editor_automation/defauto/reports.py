"""The Reporting layer: turn what was read into files an engineer can keep.

Separate from the modules on purpose. A module knows how to read its grid; it
should not also own a file format, or every new export format would mean
touching all of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from defauto import gridreader, ids
from defauto.backend import Backend, Grid


@dataclass
class Report:
    name: str
    grid: Grid
    written: Path | None = None


class Reports:
    """Named exports, plus the menu items DEF Editor offers under Reports."""

    MENU_ITEMS = ids.REPORT_ITEMS

    def __init__(self, backend: Backend, out_dir: Path | str = "exports") -> None:
        self.backend = backend
        self.out_dir = Path(out_dir)

    def _stamp(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def save(self, name: str, grid: Grid) -> Report:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
        path = self.out_dir / f"{safe}_{self._stamp()}.csv"
        gridreader.save_csv(grid, path)
        return Report(name, grid, path)

    def bundle(self, grids: Dict[str, Grid]) -> List[Report]:
        """Write several grids in one go — what the GUI's Export All does."""
        return [self.save(name, grid) for name, grid in grids.items()]
