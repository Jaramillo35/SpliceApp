"""In-app resolution of the VBOM Harness-Selection review gate.

The desktop gate: the workflow emits a macro-enabled Harness_Selection_Review
workbook and WITHHOLDS the DEFE template; the SE resolves every flagged
selection in Excel and generates the template with the macro button. These
helpers provide the same gate inside the app — apply the SE's resolved PNs
onto the selections and generate the DEFE template with the very same legacy
routine (create_formatted_output), so both paths produce identical output.
The Excel workbook remains in the bundle for whoever prefers that flow.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from splice.vbom.workflow import _load_vbom_module


def allowed_pns(review_row) -> list[str]:
    """The PN choices a review case offers (comma-joined in the frame)."""
    raw = str(review_row.get("AllowedPNs") or "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def reason_counts(review_df: pd.DataFrame) -> dict[str, int]:
    """How many cases each review reason contributes (a case may have several)."""
    counts: dict[str, int] = {}
    if review_df is None or review_df.empty:
        return counts
    for reasons in review_df["ReviewReason"].astype(str):
        for reason in reasons.split(";"):
            reason = reason.strip()
            if reason:
                counts[reason] = counts.get(reason, 0) + 1
    return counts


def apply_resolutions(selections_df: pd.DataFrame,
                      resolutions: dict[str, str]) -> pd.DataFrame:
    """Return a copy of the selections with the SE's resolved PNs applied.

    ``resolutions`` maps ReviewID ("VIN|HarnessFamily") to the chosen PN —
    exactly what the review workbook's macro writes back into the selections.
    """
    resolved = selections_df.copy()
    for review_id, pn in resolutions.items():
        vin, _, family = review_id.partition("|")
        mask = (resolved["VIN"].astype(str).str.strip() == vin.strip()) \
            & (resolved["HarnessFamily"].astype(str).str.strip() == family.strip())
        resolved.loc[mask, "SelectedHarnessPN"] = pn
        if pn.strip().upper() == "N/A":
            resolved.loc[mask, "MatchStatus"] = "NOT_APPLICABLE"
        else:
            resolved.loc[mask, "MatchStatus"] = "RESOLVED (SE)"
    return resolved


def generate_defe(my: str, program: str, selections_df: pd.DataFrame,
                  vin_matrix_df: pd.DataFrame) -> tuple[str, bytes]:
    """Produce the DEFE template workbook via the legacy routine, in memory.

    Same Template.xlsx and the same create_formatted_output the desktop
    macro path uses — one source of truth for the output format.
    """
    from splice.config import VBOM_TEMPLATES_DIR
    vbom_main_app = _load_vbom_module()
    template = VBOM_TEMPLATES_DIR / vbom_main_app.TEMPLATE_SOURCE_FILE
    with tempfile.TemporaryDirectory(prefix="vbom_defe_") as td:
        out_path = vbom_main_app.create_formatted_output(
            str(template), my, program, td, selections_df, vin_matrix_df)
        if not out_path or not Path(out_path).is_file():
            raise RuntimeError("The DEFE template could not be generated — "
                               "see the server log for the underlying error.")
        return Path(out_path).name, Path(out_path).read_bytes()
