"""Harness variant partitioning (RU-style shared worksheets).

Several harness variants can share one Master Complexity worksheet; on **row 9**
the worksheet carries variant marker columns (LEFT/RIGHT, DRIVER/PASSENGER, and
CONSOLE's CUP vs CM5/CVM). Each part-number row is marked (X/G) under exactly
one of those columns, which tells us the variant it belongs to. On generate the
worksheet is split into one file per variant.

The keyword→side map below is the seam to adapt for other programs.
"""

from __future__ import annotations

_MARK = ("X", "G")

# Row-9 marker text -> canonical variant side. CONSOLE groups CM5 and CVM into one side.
_KEYWORD_SIDE: dict[str, str] = {
    "LEFT": "LEFT", "RIGHT": "RIGHT",
    "DRIVER": "DRIVER", "PASSENGER": "PASSENGER",
    "CUP": "CUP", "CM5": "CM5/CVM", "CVM": "CM5/CVM",
}


def partition_columns(ws, sales_code_row: int = 9) -> dict[int, str]:
    """Row-9 variant marker columns on a worksheet: {column index -> canonical side}."""
    cols: dict[int, str] = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(sales_code_row, c).value
        if v is None:
            continue
        side = _KEYWORD_SIDE.get(str(v).strip().upper())
        if side:
            cols[c] = side
    return cols


def row_side(ws, row: int, part_cols: dict[int, str]) -> str:
    """The variant side a part-number row belongs to (its X/G-marked column), or ''."""
    for c, side in part_cols.items():
        v = ws.cell(row, c).value
        if v is not None and str(v).strip().upper() in _MARK:
            return side
    return ""


def ordered_sides(part_cols: dict[int, str]) -> list[str]:
    """Distinct sides in left-to-right column order (e.g. ['CUP', 'CM5/CVM'])."""
    out: list[str] = []
    for c in sorted(part_cols):
        s = part_cols[c]
        if s not in out:
            out.append(s)
    return out
