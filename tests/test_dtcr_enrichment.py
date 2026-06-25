from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from secr_enrichment_engine import match_dtcr_to_harness_family


def test_match_dtcr_to_harness_family_includes_cnum_column() -> None:
    dtcr_df = pd.DataFrame(
        [
            {
                "DTCR#": "DTCR-1",
                "Device Transmittal": "123456 - SWITCH BANK LEFT",
                "Reason for change": "Updated connector",
                "Status": "Open",
            }
        ]
    )
    dtx_df = pd.DataFrame(
        [
            {
                "Device Control Number": "123456",
                "Device Name": "SWITCH BANK LEFT",
                "Harness Family": "HF-1",
                "CNUM": "C123",
            }
        ]
    )

    result = match_dtcr_to_harness_family(dtcr_df, dtx_df)

    assert "CNUM" in result.columns
    assert result.loc[0, "CNUM"] == "C123"
    assert result.loc[0, "Harness Family"] == "HF-1"
