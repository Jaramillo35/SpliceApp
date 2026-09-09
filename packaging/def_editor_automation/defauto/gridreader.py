"""The Grid Reader layer: pull a DataGridView out as data, and write it out.

Grids are DEF Editor's primary data source, so this is deliberately the only
place that knows how to turn one into something an engineer can keep. Every
module hands its grid through here rather than exporting on its own, which is
why "export" behaves identically on ten different pages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from defauto.backend import Backend, Grid


def read(backend: Backend, automation_id: str, scope: str = "") -> Grid:
    """One grid, as it currently stands on screen."""
    return backend.grid(automation_id, scope)


def filtered(backend: Backend, automation_id: str, filter_id: str,
             needle: str, scope: str = "") -> Grid:
    """Type into the page's filter box, then read what is left.

    The filter is applied by the application, not here: typing and reading
    back is the only way to be sure the automation and the engineer looking at
    the screen are seeing the same rows.
    """
    backend.set_text(filter_id, needle, scope)
    return backend.grid(automation_id, scope)


def find(grid: Grid, column: str, value: str) -> Optional[dict]:
    """The first row whose ``column`` equals ``value``, case-insensitively."""
    index = grid.index_of(column)
    for row in grid.rows:
        if index < len(row) and row[index].strip().lower() == value.strip().lower():
            return dict(zip(grid.headers, row))
    return None


def to_csv(grid: Grid) -> str:
    return grid.to_csv()


def save_csv(grid: Grid, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(grid.to_csv(), encoding="utf-8")
    return path


def merge(grids: Sequence[Grid], label_header: str = "Source",
          labels: Sequence[str] = ()) -> Grid:
    """Stack grids that share a header row, tagging each with where it came from.

    Used by the reports layer, which routinely wants "the same grid across
    several harnesses" as one table.
    """
    if not grids:
        return Grid()
    headers = [label_header, *grids[0].headers]
    rows = []
    for grid, label in zip(grids, list(labels) + [""] * len(grids)):
        for row in grid.rows:
            rows.append([label, *row])
    return Grid(headers=headers, rows=rows)


def as_table(grid: Grid, limit: int = 0) -> str:
    """A fixed-width rendering, for the log pane and for BUILD notes."""
    rows = grid.rows[:limit] if limit else grid.rows
    widths = [len(h) for h in grid.headers]
    for row in rows:
        for i, cell in enumerate(row[:len(widths)]):
            widths[i] = max(widths[i], len(str(cell)))
    out = [" | ".join(h.ljust(w) for h, w in zip(grid.headers, widths)),
           "-+-".join("-" * w for w in widths)]
    for row in rows:
        out.append(" | ".join(str(c).ljust(w)
                              for c, w in zip(row, widths)))
    if limit and len(grid.rows) > limit:
        out.append(f"... {len(grid.rows) - limit} more row(s)")
    return "\n".join(out)
