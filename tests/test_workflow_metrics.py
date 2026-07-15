from __future__ import annotations

import pandas as pd

from metrics.workflow_metrics import (
    create_secr_counts,
    dtcr_matching_counts,
    dtx_compare_counts,
    dtx_preorder_counts,
    splice_counts,
    vbom_counts,
)


def test_splice_counts_extract_rows_entities_and_validation() -> None:
    result = {
        "option_df": pd.DataFrame({"Circuit": ["A", "A", "B"]}),
        "generated_connections_df": pd.DataFrame({"x": [1, 2]}),
        "harness_code_map_df": pd.DataFrame({"Harness PN": ["H1", "H2", "H2"]}),
        "validation_report_df": pd.DataFrame({"Status": ["PASS", "FAIL"]}),
        "can_mode": True,
        "can_validation_passed": False,
    }
    counts = splice_counts(result)
    assert counts["rows_read"] == 3
    assert counts["rows_processed"] == 2
    assert counts["circuits_processed"] == 2
    assert counts["harness_variants_processed"] == 2
    assert counts["automatic_validation_failures"] == 1
    assert counts["automatic_validation_warnings"] == 1


def test_dtx_counts_use_result_totals() -> None:
    compare_counts = dtx_compare_counts({"old_total_circuits": 7, "new_total_circuits": 9, "modified_circuit_count": 3})
    assert compare_counts["rows_read"] == 16
    preorder_counts = dtx_preorder_counts(
        {
            "summary_df": pd.DataFrame({"A": [1, 2, 3]}),
            "connector_changes_df": pd.DataFrame({"A": [1]}),
        }
    )
    assert preorder_counts["rows_read"] == 4
    assert preorder_counts["rows_processed"] == 1


def test_dtcr_matching_counts_warning_for_no_match() -> None:
    dtcr_df = pd.DataFrame({"A": [1, 2]})
    dtx_df = pd.DataFrame({"A": [1]})
    mapping_df = pd.DataFrame(
        {
            "Match Method": ["No Match", "Device Name"],
            "Harness Family": ["", "HF-1"],
        }
    )
    counts = dtcr_matching_counts(dtcr_df, dtx_df, mapping_df)
    assert counts["rows_read"] == 3
    assert counts["rows_processed"] == 2
    assert counts["automatic_validation_warnings"] == 1
    assert counts["harness_variants_processed"] == 1


def test_create_secr_counts_allow_null_entities() -> None:
    summary_df = pd.DataFrame(
        {
            "Metric": ["DTCRs Not Matched"],
            "Value": [2],
        }
    )
    counts = create_secr_counts(def_file_uploaded=True, enriched=True, enrichment_summary_df=summary_df)
    assert counts["rows_read"] is None
    assert counts["automatic_validation_warnings"] == 2


def test_vbom_counts_reads_stats_payload() -> None:
    result = {
        "metrics_stats": {
            "rows_read": 120,
            "rows_processed": 80,
            "circuits_processed": None,
            "harness_variants_processed": 6,
            "validation_warnings": 4,
        }
    }
    counts = vbom_counts(result)
    assert counts["rows_read"] == 120
    assert counts["rows_processed"] == 80
    assert counts["harness_variants_processed"] == 6
    assert counts["automatic_validation_warnings"] == 4
