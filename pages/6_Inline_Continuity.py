"""Inline Continuity Validation — load, validate, review, export.

Thin by design: it uploads files, calls :mod:`splice.inline`, and renders what
comes back. Every rule lives in the engine package.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import streamlit as st

CURRENT_DIR = Path(__file__).resolve().parent
APP_DIR = CURRENT_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from splice.common.errors import SpliceError
from splice.inline import report as inline_report
from splice.inline.complexity import read_complexity
from splice.inline.model import CONTINUOUS, NOT_IN_SUMMARY
from splice.inline.pairing import resolve
from splice.inline.readiness import BLOCKING, assess, duplicate_complexity
from splice.inline.summary import read_circuit_summary
from splice.inline.validate import run_study

K = "inline_"

st.title("Inline Continuity Validation")
st.caption(
    "Checks that circuits continue across harness interfaces. Load the Circuit "
    "Summary and the complexity file for every harness in it; the tool decides "
    "each cavity and shows you only what needs a person."
)


def _k(name: str) -> str:
    return f"{K}{name}"


# ---------------------------------------------------------------------------
# 1 · Circuit Summary
# ---------------------------------------------------------------------------
st.subheader("1 · Circuit Summary")
summary_upload = st.file_uploader(
    "Circuit Summary export (.xlsx)", type=["xlsx", "xlsm"], key=_k("summary")
)
if summary_upload is None:
    st.info("Upload the Circuit Summary to begin. It may contain every harness.")
    st.stop()

try:
    harnesses, ends = read_circuit_summary(
        summary_upload.getvalue(), summary_upload.name
    )
except SpliceError as exc:
    st.error(str(exc))
    st.stop()
except Exception as exc:  # noqa: BLE001
    st.error(f"The Circuit Summary could not be read: {exc}")
    st.stop()

st.success(
    f"{len(harnesses)} harnesses · {len(ends):,} circuit ends", icon="✅"
)

names = {h.name: def_id for def_id, h in sorted(harnesses.items(),
                                                key=lambda kv: kv[1].name)}
excluded = st.multiselect(
    "Harnesses to exclude from the study",
    list(names),
    default=[n for n in names if n.lower().endswith("test")],
    key=_k("excluded"),
    help="Excluded harnesses are counted in the summary, never silently dropped.",
)
out_of_scope = set(excluded)
in_scope = {d for d, h in harnesses.items() if h.name not in out_of_scope}

# ---------------------------------------------------------------------------
# 2 · Complexity files
# ---------------------------------------------------------------------------
st.subheader("2 · Harness Complexity files")
complexity_uploads = st.file_uploader(
    "One per harness (.xlsm / .xlsx) — extras are reported, not an error",
    type=["xlsm", "xlsx"],
    accept_multiple_files=True,
    key=_k("complexity"),
)

parsed, unreadable = [], []
for item in complexity_uploads or []:
    try:
        parsed.append(read_complexity(item.getvalue(), item.name))
    except SpliceError as exc:
        unreadable.append((item.name, str(exc)))
    except Exception as exc:  # noqa: BLE001
        unreadable.append((item.name, f"Unexpected error: {exc}"))

complexity = {}
for harness in parsed:
    complexity.setdefault(harness.def_id, harness)
    if harness.def_id in harnesses:
        complexity[harness.def_id].name = harnesses[harness.def_id].name

for name, why in unreadable:
    st.error(f"**{name}** — {why}")

needed = {d: harnesses[d].name for d in in_scope}
missing = {d: n for d, n in needed.items() if d not in complexity}
checklist = pd.DataFrame(
    [
        {
            "Harness": name,
            "DEF id": def_id,
            "Complexity": "—" if def_id in missing else "loaded",
            "Builds": (
                0 if def_id in missing else len(complexity[def_id].builds)
            ),
        }
        for def_id, name in sorted(needed.items(), key=lambda kv: kv[1])
    ]
)
st.dataframe(checklist, width="stretch", hide_index=True, height=260)

if missing:
    st.warning(
        f"**{len(missing)} harness(es) still need a complexity file:** "
        + ", ".join(sorted(missing.values()))
        + ". Their inlines will be reported as Undetermined.",
        icon="⚠️",
    )

gaps = assess(harnesses, complexity, out_of_scope) + duplicate_complexity(parsed)
blocking = [g for g in gaps if g.severity == BLOCKING]
if blocking:
    with st.expander(f"⚠ {len(blocking)} blocking issue(s) in the inputs", expanded=True):
        for gap in blocking:
            st.markdown(f"- **{gap.what}** — {gap.why}. _Affects: {gap.affects}_")

# ---------------------------------------------------------------------------
# 3 · Validate
# ---------------------------------------------------------------------------
st.subheader("3 · Validate")
if st.button("Run validation", type="primary", key=_k("run")):
    with st.spinner("Checking every cavity…"):
        pairs, unmated = resolve(ends, in_scope)
        st.session_state[_k("result")] = run_study(
            harnesses, ends, complexity, pairs, unmated, out_of_scope
        )
        st.session_state[_k("gaps")] = gaps

result = st.session_state.get(_k("result"))
if result is None:
    st.caption("Nothing has been validated yet.")
    st.stop()

# ---------------------------------------------------------------------------
# 4 · Review
# ---------------------------------------------------------------------------
st.subheader("4 · Review")
counts = result.verdict_counts()
columns = st.columns(4)
columns[0].metric("Cavities checked", f"{result.cavities_checked:,}")
columns[1].metric("Continuous", f"{counts.get(CONTINUOUS, 0):,}")
columns[2].metric(
    "Need review",
    f"{len(result.review):,}",
    delta=None if not result.review else "action required",
    delta_color="inverse" if result.review else "off",
)
columns[3].metric("Inline pairs", f"{len(result.pairs):,}")

marks = result.mark_counts
if marks:
    st.caption(
        "Marked, pending the equivalence table — "
        + " · ".join(f"**{v}** {k}" for k, v in sorted(marks.items(), key=lambda kv: -kv[1]))
    )

review = inline_report.review_frame(result)
if review.empty:
    st.success("Every cavity continues. Nothing needs review.", icon="✅")
else:
    verdicts = sorted({f.verdict for f in result.review})
    chosen = st.multiselect(
        "Verdict", verdicts, default=verdicts, key=_k("verdict_filter")
    )
    shown = review[review["Verdict"].isin(chosen)] if chosen else review
    st.dataframe(shown, width="stretch", hide_index=True, height=420)

with st.expander("Marked differences inside continuous cavities"):
    marked = inline_report.marked_frame(result)
    if marked.empty:
        st.caption("None.")
    else:
        st.caption(
            "One row per circuit — a cavity holding A934A and A934B shows both. "
            "Recorded, not judged: these wait on the wire-attribute equivalence "
            "table. **no counterpart** means that wire has no mate at the cavity, "
            "which the cavity's other option still covers."
        )
        st.dataframe(marked, width="stretch", hide_index=True, height=320)

with st.expander("Missing information and input notes"):
    stored_gaps = st.session_state.get(_k("gaps"), [])
    if stored_gaps:
        st.dataframe(
            inline_report.gaps_frame(stored_gaps), width="stretch", hide_index=True
        )
    else:
        st.caption("Nothing missing.")

with st.expander("Every cavity (audit)"):
    st.dataframe(
        inline_report.all_frame(result), width="stretch", hide_index=True, height=420
    )

with st.expander("Every circuit (audit, one row per wire)"):
    st.dataframe(
        inline_report.options_frame(result), width="stretch", hide_index=True,
        height=420,
    )

# ---------------------------------------------------------------------------
# 5 · Export
# ---------------------------------------------------------------------------
st.subheader("5 · Export")
st.download_button(
    "Download findings (.xlsx)",
    data=inline_report.build_workbook(result, st.session_state.get(_k("gaps"), [])),
    file_name="Inline_Continuity_Findings.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
    key=_k("download"),
)
