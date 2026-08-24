"""Circuit Health Check — holistic missing-circuit detection with SE gates.

Thin over :mod:`splice.inline.health`. Load a Circuit Summary plus one
complexity file per harness; the engine runs cavity continuity, option-window
coverage, and route completeness, auto-clearing every window it can prove and
queueing the rest for Systems-Engineer disposition. Dispositions persist in a
baseline file, so a rerun only surfaces new or changed findings; sign-off is
possible only with no open Blockers or Highs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent.parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from splice.common.errors import SpliceError
from splice.config import DATA_DIR
from splice.inline import health
from splice.inline.complexity import read_complexity
from splice.inline.pairing import resolve
from splice.inline.summary import read_circuit_summary

K = "hc_"
BASELINE_PATH = DATA_DIR / "inline_health" / "baseline.json"

SEV_ICON = {health.SEV_BLOCKER: "🟥", health.SEV_HIGH: "🟧", health.SEV_REVIEW: "🟨"}

KIND_LABEL = {
    "cavity": "Cavity mismatch",
    "one_sided_window": "Missing variant window",
    "route_window_gap": "Route gap",
}


def _finding_title(f) -> str:
    icon = SEV_ICON.get(f.severity, "▫️")
    kind = KIND_LABEL.get(f.kind, f.kind)
    parts = [f"{icon} [{f.severity}] {kind} · {f.inline}"]
    if f.cavity:
        parts.append(f"cavity {f.cavity}")
    if f.circuit:
        parts.append(f.circuit)
    if f.kind == "route_window_gap":
        parts.append(f"on {f.harness_with}")
    elif f.kind == "one_sided_window":
        parts.append(f"{f.harness_with} has it — missing on {f.harness_without}")
    elif f.harness_with or f.harness_without:
        parts.append(f"{f.harness_with} ↔ {f.harness_without}")
    return " · ".join(parts)


def _render_how_it_works() -> None:
    with st.expander("ℹ️ How this check works — read me first"):
        st.markdown(
            """
**What it does.** A circuit that crosses from one harness to another must have
a wire on *both* sides of the inline connector — for **every** vehicle that can
be built. This page checks that three ways:

1. **Cavity mismatch** — one harness has a wire in a cavity and the mate has
   nothing (or a different circuit) there. The classic, visible defect.
2. **Missing variant window** — both sides have wires, *but their sales-code
   conditions don't cover the same vehicles*. Example: Body_Left sends `R732`
   for every `CG3` vehicle, but Body_Right only receives it for `CG3&(CYC/CYF)`
   — so a `CG3&CY3` vehicle builds a wire on the left that dead-ends at the
   inline. The tool unions each side's conditions, subtracts one from the
   other, and checks the leftover *window* against the complexity tables: if
   real build part numbers exist in that window on the side with no wire,
   that's a finding — with the affected part numbers listed as evidence.
3. **Route gap** — a circuit is live on a harness in some option window (it
   crosses other inlines there) but has **no variant at one of its crossings**
   in that same window. This found the `A960` defect: present for
   `XZ2` vehicles at two inlines, absent at the Body_Left↔Body_Right one.

**What it needs.** The program **Circuit Summary** (the wires and their sales
codes) plus **one Harness Complexity file per harness** (which part numbers
build, with which sales codes). Files are matched by the DEF id *inside* the
complexity file, never by filename.

**Severities.**
| | meaning |
|---|---|
| 🟥 Blocker | real builds exist with a wire on one side and nothing on the other — a vehicle will be built with a dead-ended circuit |
| 🟧 High | route gap or config skew — usually real, but routing can legitimately differ by option; engineering judgment needed |
| 🟨 Review | attribute or bookkeeping differences worth a look |
| ✅ Auto-cleared | the algebra *proved* the difference is unreachable (the option window never builds) — no action needed, proof kept for audit |

**Your workflow.** ① Load files → Run. ② Check Gate 0 (missing files, stale
revisions) — findings against stale inputs are suspect. ③ Work the **Open**
tab: each finding gets a disposition — *Accepted variant* (it's fine, say
why), *Defect* (file the SECR), or *By design*. Dispositions are remembered:
the next run only shows what's new. ④ When no Blocker/High is open, **sign
off** — that records your name, the date, and the run in the baseline, and
the report workbook carries the full audit trail.
            """
        )


def _load_inputs():
    st.subheader("1 · Inputs")
    summary_file = st.file_uploader("Circuit Summary (program export)",
                                    type=["xlsx"], key=f"{K}summary")
    cx_files = st.file_uploader("Harness Complexity files (one per harness)",
                                type=["xlsm", "xlsx"], accept_multiple_files=True,
                                key=f"{K}cx")
    return summary_file, cx_files


def _run(summary_file, cx_files):
    harnesses, ends = read_circuit_summary(summary_file.getvalue(), summary_file.name)
    complexity = {}
    rejected = []
    for f in cx_files:
        try:
            cx = read_complexity(f.getvalue(), f.name)
            cx.complexity_file = f.name
            if cx.def_id in harnesses:
                complexity[cx.def_id] = cx
            else:
                rejected.append(f"{f.name} (DEF id {cx.def_id} not in the summary)")
        except SpliceError as exc:
            rejected.append(f"{f.name}: {exc}")
    pairs, unmated = resolve(ends, set(harnesses))
    result = health.analyze(harnesses, ends, complexity, pairs, unmated)
    return result, rejected


def _render_gate0(result, rejected):
    st.subheader("2 · Gate 0 — input health")
    inputs = result.inputs
    if inputs.rows:
        st.dataframe(pd.DataFrame([r.__dict__ for r in inputs.rows]),
                     use_container_width=True, hide_index=True)
    issues = []
    if rejected:
        issues.append(f"{len(rejected)} file(s) not usable: " + "; ".join(rejected))
    if inputs.missing_complexity:
        issues.append("No complexity table for: " + ", ".join(inputs.missing_complexity)
                      + " — their inlines can only be partially checked.")
    if inputs.skew_days > 30:
        issues.append(f"Revision skew of {inputs.skew_days} days between inputs "
                      f"({inputs.skew_pair}) — cross-harness findings may reflect "
                      "stale data rather than defects.")
    for issue in issues:
        st.warning(issue, icon="⚠️")
    if issues:
        return st.checkbox("I acknowledge the input issues above and want the "
                           "findings anyway", key=f"{K}ack")
    st.success("Inputs complete and consistent.", icon="✅")
    return True


def _finding_row(f, baseline, idx):
    d = baseline.get("dispositions", {}).get(f.fingerprint)
    with st.expander(_finding_title(f), expanded=False):
        st.write(f.detail)
        if f.window:
            st.code(f.window, language=None)
        cols = st.columns(2)
        if f.builds_with:
            cols[0].caption(f"Builds with the wire ({f.harness_with}): "
                            + ", ".join(f.builds_with))
        if f.builds_without:
            cols[1].caption(f"Builds WITHOUT it ({f.harness_without}): "
                            + ", ".join(f.builds_without))
        if d:
            st.info(f"Disposition: **{d['verdict']}** by {d['by']} on {d['date']} — "
                    f"{d['reason'] or 'no reason recorded'}", icon="✔️")
            return
        with st.form(key=f"{K}disp_{idx}_{f.fingerprint}"):
            c1, c2, c3 = st.columns([1, 2, 1])
            verdict = c1.selectbox("Disposition", health.DISPOSITIONS,
                                   key=f"{K}v_{idx}_{f.fingerprint}")
            reason = c2.text_input("Reason", key=f"{K}r_{idx}_{f.fingerprint}",
                                   placeholder="why this is acceptable / a defect")
            if c3.form_submit_button("Save"):
                by = st.session_state.get(f"{K}engineer", "") or "SE"
                health.disposition(baseline, f, verdict, reason, by)
                health.save_baseline(BASELINE_PATH, baseline)
                if verdict == "Defect":
                    st.toast("Recorded as Defect — file the SECR from the "
                             "SECR Database page.", icon="🗄️")
                st.rerun()


def _render_results(result):
    baseline = health.load_baseline(BASELINE_PATH)
    open_findings = result.open_findings(baseline)
    blocking = result.blocking_open(baseline)

    st.subheader("3 · Findings")
    m = st.columns(5)
    m[0].metric("Blockers open", sum(1 for f in blocking if f.severity == health.SEV_BLOCKER))
    m[1].metric("High open", sum(1 for f in blocking if f.severity == health.SEV_HIGH))
    m[2].metric("Review open", sum(1 for f in open_findings if f.severity == health.SEV_REVIEW))
    m[3].metric("Dispositioned", len(result.findings) - len(open_findings))
    m[4].metric("Auto-cleared", len(result.cleared))

    tab_open, tab_done, tab_cleared = st.tabs(
        ["Open", "Dispositioned", f"Auto-cleared proofs ({len(result.cleared)})"])
    with tab_open:
        if not open_findings:
            st.success("Nothing open — every finding is dispositioned or cleared.")
        for i, f in enumerate(open_findings):
            _finding_row(f, baseline, i)
    with tab_done:
        done = [f for f in result.findings if f not in open_findings]
        for i, f in enumerate(done):
            _finding_row(f, baseline, 1000 + i)
    with tab_cleared:
        if result.cleared:
            st.caption("Windows the algebra proved unreachable — no SE action "
                       "needed; kept for audit.")
            st.dataframe(pd.DataFrame([p.__dict__ for p in result.cleared]),
                         use_container_width=True, hide_index=True)

    st.subheader("4 · Sign-off & report")
    c1, c2, c3 = st.columns([2, 1, 1])
    c1.text_input("Systems Engineer", key=f"{K}engineer", placeholder="your name")
    can_sign = not blocking
    if c2.button("Sign off this run", disabled=not can_sign,
                 help=None if can_sign else
                 "Open Blockers/Highs must be dispositioned first"):
        health.sign_off(baseline, st.session_state.get(f"{K}engineer", "") or "SE",
                        f"{len(result.findings)} findings, "
                        f"{len(result.cleared)} auto-cleared")
        health.save_baseline(BASELINE_PATH, baseline)
        st.success("Run signed off and recorded in the baseline.")
    c3.download_button(
        "⬇ Health report (.xlsx)",
        data=health.render_report(result, baseline),
        file_name="Circuit_Health_Report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    if baseline.get("signoffs"):
        last = baseline["signoffs"][-1]
        st.caption(f"Last sign-off: {last['by']} on {last['date']}")


def render() -> None:
    st.title("Circuit Health Check")
    st.caption(
        "Catches missing circuits the cavity check cannot see: option windows "
        "with real builds but no wire, and circuits absent from one inline "
        "crossing while live elsewhere. Provable variant-splitting is cleared "
        "automatically; everything else queues for your disposition."
    )
    _render_how_it_works()

    summary_file, cx_files = _load_inputs()
    if not summary_file or not cx_files:
        st.info("Load the Circuit Summary and the complexity files to begin.",
                icon="📄")
        return

    if st.button("Run health check", type="primary"):
        with st.spinner("Analyzing every inline, cavity, and option window…"):
            try:
                st.session_state[f"{K}result"] = _run(summary_file, cx_files)
            except SpliceError as exc:
                st.error(str(exc))
                return

    stored = st.session_state.get(f"{K}result")
    if not stored:
        return
    result, rejected = stored
    if _render_gate0(result, rejected):
        _render_results(result)


render()
