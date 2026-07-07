from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiring_harness_processor import (
    analyze_candidate_code_variability,
    generate_sales_code_expression,
    validate_generated_expression,
)


def test_analyze_candidate_code_variability_flags_constant_codes() -> None:
    harness_code_map = {
        "PN1": {"501", "AAA"},
        "PN2": {"501", "BBB"},
        "PN3": {"501", "AAA", "BBB"},
    }

    summary = analyze_candidate_code_variability(harness_code_map, {"501", "AAA", "BBB", "ZZZ"})

    assert summary["always_present"] == {"501"}
    assert summary["always_absent"] == {"ZZZ"}
    assert summary["discriminating"] == {"AAA", "BBB"}


def test_generate_sales_code_expression_can_drop_standard_501() -> None:
    harness_code_map = {
        "PN1": {"501", "AAA"},
        "PN2": {"501", "BBB"},
        "PN3": {"501", "AAA", "BBB"},
    }

    expr = generate_sales_code_expression(
        target_harnesses=["PN1", "PN3"],
        harness_code_map=harness_code_map,
        candidate_codes={"501", "AAA", "BBB"},
        optimize_constants=True,
    )

    assert "501" not in expr
    assert validate_generated_expression(expr, ["PN1", "PN3"], harness_code_map)