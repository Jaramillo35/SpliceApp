"""The matrix CSV's delimiter is decided by its header line, not by luck."""

from __future__ import annotations

import pytest

from splice.hrncmp import engine


def test_comma_matrix_is_read_as_columns():
    data = b"CKT,QA1,QA2\nQK101,X,\nQK102,,X\n"
    df = engine.read_matrix_csv(data)
    assert list(df.columns) == ["CKT", "QA1", "QA2"]
    assert df.iloc[0, 1] == "X"


def test_semicolon_matrix_still_reads():
    data = b"CKT;QA1;QA2\nQK101;X;\n"
    df = engine.read_matrix_csv(data)
    assert list(df.columns) == ["CKT", "QA1", "QA2"]


def test_bom_and_tabs_are_handled():
    assert engine.matrix_delimiter(b"\xef\xbb\xbfCKT\tQA1\n") == "\t"
    assert engine.matrix_delimiter(b"CKT;QA1,QB1\n") == ";" or engine.matrix_delimiter(b"CKT;QA1;QB1\n") == ";"


def test_a_one_column_file_is_refused_not_charted():
    with pytest.raises(ValueError):
        engine.read_matrix_csv(b"CKT QA1 QA2\nQK101 X\n")
