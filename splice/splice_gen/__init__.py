"""Splice generation — harness complexity + option logic -> splice workbook.

The implementation lives in :mod:`splice.splice_gen.processor`; the public entry
points used by the UI and by scripted/agent callers are re-exported here.
"""

from __future__ import annotations

from splice.splice_gen.processor import (
    evaluate_expression_against_all_pns,
    generate_expression_for_selected_pns,
    generate_sales_code_expression,
    get_candidate_codes_from_option_df,
    get_selected_harness_pns,
    run_analysis,
    run_analysis_from_option_df,
    simplify_expression_for_display,
    validate_generated_expression,
)

__all__ = [
    "evaluate_expression_against_all_pns",
    "generate_expression_for_selected_pns",
    "generate_sales_code_expression",
    "get_candidate_codes_from_option_df",
    "get_selected_harness_pns",
    "run_analysis",
    "run_analysis_from_option_df",
    "simplify_expression_for_display",
    "validate_generated_expression",
]
