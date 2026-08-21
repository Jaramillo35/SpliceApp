"""Match DTCR records to CNUM / Harness Family.

Canonical implementation, extracted verbatim from the former
``dtx_compare_engine`` (the version selected during the Phase 2 DTCR review).
``secr_enrichment_engine`` now delegates here instead of keeping its own,
divergent copy.
"""

from __future__ import annotations

import pandas as pd

from secrdb.core.common.text import (
    extract_bulletin_number,
    extract_transmittal_number,
    normalize_match_text,
    normalize_value,
    split_delimited_values,
)

__all__ = [
    "DTCR_MATCHING_COLUMNS",
    "prepare_dtcr_for_matching",
    "match_dtcr_to_harness_family",
]

DTCR_MATCHING_COLUMNS = [
    "DTCR#",
    "Device Transmittal",
    "Extracted Device Control Number",
    "Reason for change",
    "Status",
    "Bulletin",
    "Match Method",
    "Matched DTx Value",
    "CNUM",
    "Harness Family",
]

_DTCR_COLUMN_ALIASES = {
    "DTCR#": ["dtcr#", "dtcr #", "dtcr number", "dtcr no", "dtcr"],
    "Device Transmittal": ["device transmittal", "transmittal", "device trans"],
    "Reason for change": ["reason for change", "reason for", "reason"],
    "Status": ["status", "request action", "action"],
}


def prepare_dtcr_for_matching(dtcr_df: pd.DataFrame) -> pd.DataFrame:
    """Map arbitrary DTCR-report columns to the canonical names used here.

    Resolves column-name variants (case-insensitively), normalizes the values,
    and drops rows with a blank ``DTCR#`` (wrapped/continuation rows). Raises
    ``ValueError`` if the two mandatory columns cannot be located.
    """
    lower_columns = {str(column).strip().lower(): column for column in dtcr_df.columns}

    resolved: dict[str, str | None] = {}
    for canonical, variants in _DTCR_COLUMN_ALIASES.items():
        resolved[canonical] = None
        for variant in variants:
            if variant in lower_columns:
                resolved[canonical] = lower_columns[variant]
                break

    if resolved["DTCR#"] is None or resolved["Device Transmittal"] is None:
        raise ValueError("DTCR report must include DTCR# and Device Transmittal columns.")

    prepared = pd.DataFrame()
    for canonical in _DTCR_COLUMN_ALIASES:
        source = resolved[canonical]
        prepared[canonical] = (
            dtcr_df[source].map(normalize_value) if source is not None else ""
        )
    prepared = prepared[prepared["DTCR#"] != ""].reset_index(drop=True)
    return prepared


def match_dtcr_to_harness_family(dtcr_df: pd.DataFrame, dtx_df: pd.DataFrame) -> pd.DataFrame:
    """Match each DTCR to CNUM / Harness Family.

    Priority: (1) Device Control Number, then (2) Device Name substring match.
    A DCN cell in ``dtx_df`` may hold several delimited numbers; all are indexed,
    and every matching row's CNUM and Harness Family are aggregated.

    Parameters
    ----------
    dtcr_df:
        A DTCR report frame. Column-name variants are resolved automatically.
    dtx_df:
        A DTx circuits frame with ``Device Control Number``, ``Device Name``,
        ``CNUM`` and ``Harness Family`` columns.

    Returns
    -------
    pandas.DataFrame
        One row per DTCR, with the columns in :data:`DTCR_MATCHING_COLUMNS`.
    """
    prepared = prepare_dtcr_for_matching(dtcr_df)

    dcn_index: dict[str, list[int]] = {}
    for row_position, value in enumerate(dtx_df["Device Control Number"].tolist()):
        for token in split_delimited_values(value):
            dcn_index.setdefault(token, []).append(row_position)

    name_frame = dtx_df.drop_duplicates(subset=["Device Name"]).reset_index(drop=True)

    results: list[dict[str, object]] = []
    for _, row in prepared.iterrows():
        dtcr_num = row["DTCR#"]
        device_transmittal = row["Device Transmittal"]
        reason = row["Reason for change"]
        status = row["Status"]
        bulletin = extract_bulletin_number(reason)
        extracted_dcn = extract_transmittal_number(device_transmittal)

        match_method = "No Match"
        matched_dtx_value = ""
        harness_family = ""
        cnum = ""

        if extracted_dcn and extracted_dcn in dcn_index:
            matching_rows = dtx_df.iloc[dcn_index[extracted_dcn]]
            cnum_values = [
                value for value in matching_rows["CNUM"].map(normalize_value).tolist() if value
            ]
            family_values = [
                value
                for value in matching_rows["Harness Family"].map(normalize_value).tolist()
                if value
            ]
            cnum = ", ".join(dict.fromkeys(cnum_values))
            harness_family = ", ".join(dict.fromkeys(family_values))
            matched_dtx_value = extracted_dcn
            match_method = "Device Control Number"

        if match_method == "No Match" and device_transmittal:
            normalized_transmittal = normalize_match_text(device_transmittal)
            for _, dtx_row in name_frame.iterrows():
                device_name = normalize_value(dtx_row.get("Device Name", ""))
                if not device_name:
                    continue
                normalized_name = normalize_match_text(device_name)
                if normalized_name and normalized_name in normalized_transmittal:
                    harness_family = normalize_value(dtx_row.get("Harness Family", ""))
                    matched_dtx_value = device_name
                    cnum = normalize_value(dtx_row.get("CNUM", ""))
                    match_method = "Device Name"
                    break

        results.append(
            {
                "DTCR#": dtcr_num,
                "Device Transmittal": device_transmittal,
                "Extracted Device Control Number": extracted_dcn or "",
                "Reason for change": reason,
                "Status": status,
                "Bulletin": bulletin,
                "Match Method": match_method,
                "Matched DTx Value": matched_dtx_value,
                "CNUM": cnum,
                "Harness Family": harness_family,
            }
        )

    return pd.DataFrame(results, columns=DTCR_MATCHING_COLUMNS)
