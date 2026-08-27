"""Applicability marks in individual harness complexity files.

"X" is the standard mark. "O" is a hand-entered variant that appears in real
files; it means the same thing and must not be dropped — dropping it made a
harness disappear from every VIN that needed the code, with no warning.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest
from openpyxl import Workbook

from splice.vbom.workflow import _load_vbom_module

vbom = _load_vbom_module()


def _complexity(marks: list[str]) -> pathlib.Path:
    """One harness complexity file: a single PN marked with ``marks``."""
    codes = [f"C{i}{i}{i}"[:3] for i in range(len(marks))]
    codes = ["AHT", "CJK", "RS3", "XH3", "LEQ"][:len(marks)]
    wb = Workbook()
    ws = wb.active
    ws.title = "Complexity"
    ws.append(["ID=11661", *codes])
    ws.append(["68720520AA", *marks])
    path = pathlib.Path(tempfile.mkdtemp()) / \
        "Harness_Complexity_28DT_X1_TEST_01-01-2026.xlsm"
    wb.save(path)
    return path


def _read(marks: list[str]):
    _df, _codes, rows = vbom.read_complexity_sheet(str(_complexity(marks)))
    pn, applicable, giveaway = rows[0]
    return applicable, giveaway


class TestApplicabilityMarks:
    def test_x_marks_the_code_as_carried(self):
        applicable, _ = _read(["X", ""])
        assert applicable == {"AHT"}

    def test_o_is_treated_as_x(self):
        applicable, giveaway = _read(["O", ""])
        assert applicable == {"AHT"}, "an O mark must count as applicable"
        assert giveaway == set()

    def test_marks_are_case_insensitive(self):
        assert _read(["x", ""])[0] == {"AHT"}
        assert _read(["o", ""])[0] == {"AHT"}

    def test_g_stays_a_giveaway_not_an_applicable_code(self):
        applicable, giveaway = _read(["G", ""])
        assert applicable == set() and giveaway == {"AHT"}

    def test_mixed_marks_on_one_part(self):
        applicable, giveaway = _read(["X", "O", "G", ""])
        assert applicable == {"AHT", "CJK"}
        assert giveaway == {"RS3"}

    def test_blank_and_unknown_marks_are_not_applicable(self):
        # Anything that is not a recognised mark stays out, so a stray note or
        # a dash cannot silently make a part applicable.
        applicable, giveaway = _read(["", "-", "?", "N"])
        assert applicable == set() and giveaway == set()

    def test_whitespace_around_a_mark_is_tolerated(self):
        assert _read([" X ", ""])[0] == {"AHT"}
        assert _read([" o ", ""])[0] == {"AHT"}

    def test_declared_mark_sets(self):
        assert vbom.APPLICABLE_MARKS == frozenset({"X", "O"})
        assert vbom.GIVEAWAY_MARK == "G"


class TestGuideMatchesBehaviour:
    def test_guide_documents_o_as_applicable(self):
        from splice.vbom.guide import GUIDE_MD
        assert "accepted as the same thing" in GUIDE_MD
        # the old, now-wrong claim must be gone
        assert "read as *not applicable*, silently" not in GUIDE_MD
