"""An invented programme for exercising Splice Generation.

The engine had no fixture of its own. The demo showcase ships a Splice
Generation input, but every circuit in it has exactly one endpoint, so the
generator produces no configurations and no connections from it — which is
why nine of the package's ten exported functions had never been called by a
test.

This builds a small input workbook in memory, shaped so that generation
actually happens and so the shapes that matter are all present:

Harness (5 part numbers, codes AAA / BBB / CCC)
  99000001AA  AAA
  99000002AA  AAA BBB
  99000003AA  BBB
  99000004AA  CCC
  99000005AA  (none)

Circuits
  CKT_PAIR    two endpoints, unconditional      -> a direct connection
  CKT_SPLICE  three endpoints, unconditional    -> a splice
  CKT_WIDE    four endpoints, mixed conditions  -> a splice with variants
  CKT_MIXED   two endpoints on "AAA&BBB/CCC"    -> the precedence case: it
              reads differently under the two grammars the app used to have,
              so any test on it pins which grammar is in force
  CKT_UNIV    two endpoints on a bare "501"     -> the universal-code rule
"""

from __future__ import annotations

import io

import pandas as pd

HARNESS_PNS = ["99000001AA", "99000002AA", "99000003AA", "99000004AA",
               "99000005AA"]
CODES = ["AAA", "BBB", "CCC"]

#: part number -> the codes it carries
CARRIES = {
    "99000001AA": {"AAA"},
    "99000002AA": {"AAA", "BBB"},
    "99000003AA": {"BBB"},
    "99000004AA": {"CCC"},
    "99000005AA": set(),
}

#: (CNUM, pin, circuit, sales code)
ENDPOINTS = [
    ("D100A", "1", "CKT_PAIR", ""),
    ("D101A", "1", "CKT_PAIR", ""),

    ("D200A", "1", "CKT_SPLICE", ""),
    ("D201A", "1", "CKT_SPLICE", ""),
    ("D202A", "1", "CKT_SPLICE", ""),

    ("D300A", "1", "CKT_WIDE", "AAA"),
    ("D301A", "1", "CKT_WIDE", "BBB"),
    ("D302A", "2", "CKT_WIDE", ""),
    ("D303A", "1", "CKT_WIDE", "-CCC"),

    # the operator-precedence case, kept deliberately unparenthesised
    ("D400A", "1", "CKT_MIXED", "AAA&BBB/CCC"),
    ("D401A", "1", "CKT_MIXED", "AAA&BBB/CCC"),

    ("D500A", "1", "CKT_UNIV", "501"),
    ("D501A", "1", "CKT_UNIV", "501"),
]


def complexity_frame() -> pd.DataFrame:
    """The Complexity sheet: one row per part number, an X under each code."""
    rows = []
    for pn in HARNESS_PNS:
        row = {"Harness PN": pn}
        row.update({code: ("X" if code in CARRIES[pn] else "") for code in CODES})
        rows.append(row)
    return pd.DataFrame(rows)


def option_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [{"CNUM": c, "Pin": p, "Circuit": ckt, "Sales Code": sc}
         for c, p, ckt, sc in ENDPOINTS])


def workbook_bytes() -> bytes:
    """The two sheets the loaders look for, as a real .xlsx."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        complexity_frame().to_excel(writer, sheet_name="Complexity", index=False)
        option_frame().to_excel(writer, sheet_name="OptionPerCkt", index=False)
    return buf.getvalue()


def write_input(path) -> "pathlib.Path":  # noqa: F821 - annotation only
    import pathlib
    target = pathlib.Path(path)
    target.write_bytes(workbook_bytes())
    return target


def harness_code_map() -> dict:
    """What ``load_complexity_matrix`` produces, without the file round trip."""
    return {pn: set(codes) for pn, codes in CARRIES.items()}
