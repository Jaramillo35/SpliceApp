from __future__ import annotations

from typing import Any

import pandas as pd


def _safe_len(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(len(value))
    except Exception:
        return 0


def _unique_non_empty(series: pd.Series) -> int:
    cleaned = series.astype(str).str.strip()
    cleaned = cleaned[cleaned != ""]
    return int(cleaned.nunique())


def splice_counts(result: dict[str, Any]) -> dict[str, int | None]:
    option_df = result.get("option_df", pd.DataFrame())
    generated_connections_df = result.get("generated_connections_df", pd.DataFrame())
    harness_map_df = result.get("harness_code_map_df", pd.DataFrame())
    validation_df = result.get("validation_report_df", pd.DataFrame())

    fail_count = 0
    warning_count = 0
    if not validation_df.empty and "Status" in validation_df.columns:
        statuses = validation_df["Status"].astype(str).str.upper().str.strip()
        fail_count = int((statuses == "FAIL").sum())

    if result.get("can_mode") and not result.get("can_validation_passed", True):
        warning_count = 1

    harness_count = None
    if not harness_map_df.empty and "Harness PN" in harness_map_df.columns:
        harness_count = _unique_non_empty(harness_map_df["Harness PN"])

    circuit_count = None
    if not option_df.empty and "Circuit" in option_df.columns:
        circuit_count = _unique_non_empty(option_df["Circuit"])

    return {
        "rows_read": _safe_len(option_df),
        # rows_processed is defined as output engineering rows generated for connection output.
        "rows_processed": _safe_len(generated_connections_df),
        "circuits_processed": circuit_count,
        "harness_variants_processed": harness_count,
        "automatic_validation_errors": fail_count,
        "automatic_validation_warnings": warning_count,
        "automatic_validation_failures": fail_count,
    }


def dtx_compare_counts(result: dict[str, Any]) -> dict[str, int | None]:
    old_total = int(result.get("old_total_circuits", 0) or 0)
    new_total = int(result.get("new_total_circuits", 0) or 0)
    modified_total = int(result.get("modified_circuit_count", 0) or 0)

    return {
        "rows_read": old_total + new_total,
        "rows_processed": old_total + new_total,
        "circuits_processed": old_total + new_total,
        "harness_variants_processed": None,
        "automatic_validation_errors": 0,
        "automatic_validation_warnings": 0,
        "automatic_validation_failures": 0,
        # Modified circuit count is captured as an additional warning-like signal in UI summary only.
        "modified_circuits": modified_total,
    }


def dtx_preorder_counts(result: dict[str, Any]) -> dict[str, int | None]:
    summary_df = result.get("summary_df", pd.DataFrame())
    connector_changes_df = result.get("connector_changes_df", pd.DataFrame())

    return {
        "rows_read": _safe_len(summary_df) + _safe_len(connector_changes_df),
        "rows_processed": _safe_len(connector_changes_df),
        "circuits_processed": None,
        "harness_variants_processed": None,
        "automatic_validation_errors": 0,
        "automatic_validation_warnings": 0,
        "automatic_validation_failures": 0,
    }


def dtcr_matching_counts(
    dtcr_df: pd.DataFrame,
    dtx_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
) -> dict[str, int | None]:
    no_match_count = 0
    harness_count = None

    if not mapping_df.empty:
        if "Match Method" in mapping_df.columns:
            no_match_count = int((mapping_df["Match Method"].astype(str).str.strip() == "No Match").sum())
        if "Harness Family" in mapping_df.columns:
            harness_count = _unique_non_empty(mapping_df["Harness Family"])

    return {
        "rows_read": _safe_len(dtcr_df) + _safe_len(dtx_df),
        "rows_processed": _safe_len(mapping_df),
        "circuits_processed": None,
        "harness_variants_processed": harness_count,
        "automatic_validation_errors": 0,
        "automatic_validation_warnings": no_match_count,
        "automatic_validation_failures": 0,
    }


def create_secr_counts(
    *,
    def_file_uploaded: bool,
    enriched: bool,
    enrichment_summary_df: pd.DataFrame | None,
) -> dict[str, int | None]:
    warnings = 0
    if enriched and enrichment_summary_df is not None and not enrichment_summary_df.empty:
        try:
            warnings = int(
                enrichment_summary_df.loc[
                    enrichment_summary_df["Metric"] == "DTCRs Not Matched", "Value"
                ].iloc[0]
            )
        except Exception:
            warnings = 0

    return {
        "rows_read": None,
        "rows_processed": None,
        "circuits_processed": None,
        "harness_variants_processed": None,
        "automatic_validation_errors": 0,
        "automatic_validation_warnings": warnings,
        "automatic_validation_failures": 0,
        "input_present": 1 if def_file_uploaded else 0,
    }


def vbom_counts(result: dict[str, Any]) -> dict[str, int | None]:
    stats = result.get("metrics_stats", {}) if isinstance(result, dict) else {}
    return {
        "rows_read": stats.get("rows_read"),
        "rows_processed": stats.get("rows_processed"),
        "circuits_processed": stats.get("circuits_processed"),
        "harness_variants_processed": stats.get("harness_variants_processed"),
        "automatic_validation_errors": 0,
        "automatic_validation_warnings": stats.get("validation_warnings"),
        "automatic_validation_failures": 0,
    }
