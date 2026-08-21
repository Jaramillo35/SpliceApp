"""Turning findings into something an engineer reads and files.

Two outputs from one set of findings: frames for the screen, and a workbook to
attach to a review. Both lead with what needs attention, because the point of
the feature is that most cavities never need a person.
"""

from __future__ import annotations

import io
from typing import Dict, List

import pandas as pd

from splice.inline.model import Finding, Gap, StudyResult

REVIEW_COLUMNS = [
    ("verdict", "Verdict"),
    ("inline", "Inline"),
    ("harness_a", "Harness A"),
    ("harness_b", "Harness B"),
    ("cavity", "Cavity"),
    ("circuits_a", "Circuits A"),
    ("circuits_b", "Circuits B"),
    ("sales_codes_a", "Sales code A"),
    ("sales_codes_b", "Sales code B"),
    ("reason", "Reason"),
]

ALL_COLUMNS = REVIEW_COLUMNS + [("marks", "Marked differences")]


def _row(finding: Finding, columns) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, label in columns:
        value = getattr(finding, key, "")
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if str(v))
        out[label] = value
    return out


def review_frame(result: StudyResult) -> pd.DataFrame:
    """Only what needs a person."""
    return pd.DataFrame([_row(f, REVIEW_COLUMNS) for f in result.review])


def all_frame(result: StudyResult) -> pd.DataFrame:
    """Every cavity, for audit."""
    return pd.DataFrame([_row(f, ALL_COLUMNS) for f in result.findings])


def marked_frame(result: StudyResult) -> pd.DataFrame:
    """Attribute differences, **one circuit per row**.

    A cavity holding ``A934A`` and ``A934B`` produces two rows, not one row with
    a comma-joined list — the difference belongs to a specific wire, and joining
    them makes it impossible to tell which one carries it.
    """
    rows = []
    for finding in result.findings:
        if finding.needs_review or not finding.marks:
            continue
        for option in finding.options:
            if not option.marks:
                continue
            rows.append(
                {
                    "Inline": finding.inline,
                    "Harness A": finding.harness_a,
                    "Harness B": finding.harness_b,
                    "Cavity": finding.cavity,
                    "Circuit A": option.label_a or "—",
                    "Sales code A": option.sales_code_a or "(standard)",
                    "Size A": option.size_a,
                    "Material A": option.material_a,
                    "Circuit B": option.label_b or "—",
                    "Sales code B": option.sales_code_b or "(standard)",
                    "Size B": option.size_b,
                    "Material B": option.material_b,
                    "Marked": ", ".join(option.marks),
                }
            )
    return pd.DataFrame(rows)


def options_frame(result: StudyResult) -> pd.DataFrame:
    """Every wire at every cavity, one per row — the full audit view."""
    rows = []
    for finding in result.findings:
        if not finding.options:
            rows.append(
                {
                    "Verdict": finding.verdict,
                    "Inline": finding.inline,
                    "Cavity": finding.cavity,
                    "Circuit A": ", ".join(finding.circuits_a) or "—",
                    "Sales code A": ", ".join(finding.sales_codes_a) or "—",
                    "Circuit B": ", ".join(finding.circuits_b) or "—",
                    "Sales code B": ", ".join(finding.sales_codes_b) or "—",
                    "Marked": "",
                    "Reason": finding.reason,
                }
            )
            continue
        for option in finding.options:
            rows.append(
                {
                    "Verdict": finding.verdict,
                    "Inline": finding.inline,
                    "Cavity": finding.cavity,
                    "Circuit A": option.label_a or "—",
                    "Sales code A": option.sales_code_a or "(standard)",
                    "Circuit B": option.label_b or "—",
                    "Sales code B": option.sales_code_b or "(standard)",
                    "Marked": ", ".join(option.marks),
                    "Reason": finding.reason,
                }
            )
    return pd.DataFrame(rows)


def gaps_frame(gaps: List[Gap]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Severity": g.severity,
                "What is missing": g.what,
                "Why it is needed": g.why,
                "What it affects": g.affects,
            }
            for g in gaps
        ]
    )


def summary_frame(result: StudyResult) -> pd.DataFrame:
    counts = result.verdict_counts()
    total = sum(counts.values()) or 1
    return pd.DataFrame(
        [
            {"Verdict": k, "Cavities": v, "Share": f"{100 * v / total:.1f}%"}
            for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
        ]
    )


def build_workbook(result: StudyResult, gaps: List[Gap]) -> bytes:
    """One .xlsx: summary, the review queue, marked differences, everything."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        summary_frame(result).to_excel(writer, sheet_name="Summary", index=False)
        review = review_frame(result)
        if review.empty:
            review = pd.DataFrame([{"Verdict": "Nothing to review"}])
        review.to_excel(writer, sheet_name="Review", index=False)
        marked = marked_frame(result)
        if not marked.empty:
            marked.to_excel(writer, sheet_name="Marked differences", index=False)
        if gaps:
            gaps_frame(gaps).to_excel(writer, sheet_name="Missing information",
                                      index=False)
        all_frame(result).to_excel(writer, sheet_name="All cavities", index=False)
        options_frame(result).to_excel(
            writer, sheet_name="All circuits", index=False
        )
    return buffer.getvalue()
