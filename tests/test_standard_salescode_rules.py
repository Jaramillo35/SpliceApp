from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiring_harness_processor import (
    Endpoint,
    _choose_anchor_endpoint,
    build_harness_presence_matrix,
    generate_sales_code_expression,
    parse_sales_code_expression,
)


def test_parse_sales_code_expression_treats_501_as_always_present() -> None:
    parsed = parse_sales_code_expression("501&AAA&-BBB")

    assert parsed.postfix_tokens == ["AAA", "BBB", "NOT", "&"]
    assert parsed.symbols == {"AAA", "BBB"}


def test_build_harness_presence_matrix_applies_501_to_all_harnesses() -> None:
    harness_code_map = {
        "PN1": {"AAA"},
        "PN2": {"BBB"},
        "PN3": {"AAA", "BBB"},
    }
    option_df = pd.DataFrame(
        [
            {"CNUM": "C1", "Pin": "1", "Circuit": "X1", "Sales Code": "501"},
            {"CNUM": "C2", "Pin": "2", "Circuit": "X1", "Sales Code": "AAA"},
        ]
    )

    _, matrix = build_harness_presence_matrix(harness_code_map, option_df)

    assert sorted((e.cnum, e.sales_code) for e in matrix["PN1"]["X1"]) == [("C1", "501"), ("C2", "AAA")]
    assert sorted((e.cnum, e.sales_code) for e in matrix["PN2"]["X1"]) == [("C1", "501")]
    assert sorted((e.cnum, e.sales_code) for e in matrix["PN3"]["X1"]) == [("C1", "501"), ("C2", "AAA")]


def test_generate_sales_code_expression_never_emits_501() -> None:
    harness_code_map = {
        "PN1": {"501", "AAA"},
        "PN2": {"501", "BBB"},
        "PN3": {"501", "AAA", "BBB"},
    }

    expr = generate_sales_code_expression(
        target_harnesses=["PN1", "PN3"],
        harness_code_map=harness_code_map,
        candidate_codes={"501", "AAA", "BBB"},
    )

    assert expr == "AAA"


def test_choose_anchor_endpoint_prefers_501_rule_row() -> None:
    endpoints = [
        Endpoint(cnum="OPT", pin="2", circuit="X1", sales_code="AAA"),
        Endpoint(cnum="STD", pin="1", circuit="X1", sales_code="501"),
    ]

    anchor = _choose_anchor_endpoint(endpoints)

    assert anchor.cnum == "STD"