from __future__ import annotations

import os
from typing import Any

import streamlit as st

from .calculations import clamp_optional_count, to_minutes
from .tracker import MetricsTracker


def render_pre_run_questions(
    tracker: MetricsTracker,
    workflow_id: str,
    *,
    ask_circuits_if_unknown: bool,
    ask_harness_if_unknown: bool,
) -> dict[str, Any]:
    prefill = tracker.get_latest_baseline_prefill(workflow_id)
    baseline_minutes_prefill = prefill.get("baseline_minutes")
    baseline_touchpoints_prefill = prefill.get("baseline_manual_touchpoints")

    default_hours = int((baseline_minutes_prefill or 0) // 60) if baseline_minutes_prefill else 0
    default_minutes = int((baseline_minutes_prefill or 0) % 60) if baseline_minutes_prefill else 0

    with st.expander("Impact Metrics (optional pre-run questions)", expanded=False):
        st.caption(
            "Do not enter confidential engineering data. These questions capture baseline effort only."
        )

        baseline_skip = st.checkbox(
            "Skip baseline time question",
            value=False,
            key=f"metrics_{workflow_id}_baseline_skip",
        )
        baseline_hours = st.number_input(
            "Before using this tool, approximately how long would this workflow take manually? (hours)",
            min_value=0,
            max_value=999,
            value=default_hours,
            step=1,
            key=f"metrics_{workflow_id}_baseline_hours",
        )
        baseline_minutes = st.number_input(
            "Before using this tool, approximately how long would this workflow take manually? (minutes)",
            min_value=0,
            max_value=59,
            value=default_minutes,
            step=1,
            key=f"metrics_{workflow_id}_baseline_minutes",
        )

        touchpoint_skip = st.checkbox(
            "I do not know baseline manual touchpoints",
            value=False,
            key=f"metrics_{workflow_id}_baseline_touchpoints_skip",
        )
        baseline_manual_touchpoints = st.number_input(
            "Approximately how many manual steps or touchpoints were normally required?",
            min_value=0,
            max_value=10000,
            value=int(baseline_touchpoints_prefill or 0),
            step=1,
            key=f"metrics_{workflow_id}_baseline_touchpoints",
        )

        user_circuit_count = None
        user_harness_count = None

        if ask_circuits_if_unknown:
            circuit_skip = st.checkbox(
                "I do not know approximate circuit count",
                value=False,
                key=f"metrics_{workflow_id}_circuit_skip",
            )
            circuit_val = st.number_input(
                "Approximate circuits processed (only if unknown to the app)",
                min_value=0,
                max_value=1000000,
                value=0,
                step=1,
                key=f"metrics_{workflow_id}_circuit_value",
            )
            user_circuit_count = None if circuit_skip else clamp_optional_count(int(circuit_val))

        if ask_harness_if_unknown:
            harness_skip = st.checkbox(
                "I do not know approximate harness variant count",
                value=False,
                key=f"metrics_{workflow_id}_harness_skip",
            )
            harness_val = st.number_input(
                "Approximate harness variants processed (only if unknown to the app)",
                min_value=0,
                max_value=1000000,
                value=0,
                step=1,
                key=f"metrics_{workflow_id}_harness_value",
            )
            user_harness_count = None if harness_skip else clamp_optional_count(int(harness_val))

    baseline_minutes_value = None
    if not baseline_skip:
        baseline_minutes_value = to_minutes(int(baseline_hours), int(baseline_minutes))

    baseline_touchpoints_value = None if touchpoint_skip else clamp_optional_count(int(baseline_manual_touchpoints))

    return {
        "baseline_minutes": baseline_minutes_value,
        "baseline_manual_touchpoints": baseline_touchpoints_value,
        "user_reported_circuits_processed": user_circuit_count,
        "user_reported_harness_variants_processed": user_harness_count,
    }


def render_post_run_feedback(
    tracker: MetricsTracker,
    workflow_id: str,
    *,
    run_id: str,
    processing_seconds: float,
    pre_run_answers: dict[str, Any],
) -> None:
    feedback_state_key = "metrics_feedback_submitted_runs"
    submitted = st.session_state.get(feedback_state_key, set())
    if run_id in submitted:
        return

    st.markdown("---")
    st.subheader("Optional impact feedback")

    with st.form(f"metrics_post_feedback_{workflow_id}_{run_id}"):
        remaining_skip = st.checkbox(
            "I do not know remaining manual touchpoints",
            value=False,
            key=f"metrics_{workflow_id}_{run_id}_remaining_skip",
        )
        remaining_touchpoints = st.number_input(
            "How many manual steps were still required after using the tool?",
            min_value=0,
            max_value=10000,
            value=0,
            step=1,
            key=f"metrics_{workflow_id}_{run_id}_remaining_steps",
        )

        found_problems = st.selectbox(
            "Did the tool identify any problems you might not have found before release?",
            options=["Skip", "No", "Yes"],
            index=0,
            key=f"metrics_{workflow_id}_{run_id}_found_problems",
        )

        error_count = None
        if found_problems == "Yes":
            error_count = st.number_input(
                "Approximate number of additional problems identified",
                min_value=0,
                max_value=100000,
                value=1,
                step=1,
                key=f"metrics_{workflow_id}_{run_id}_error_count",
            )

        rating = st.selectbox(
            "Optional usefulness rating",
            options=["Skip", "1", "2", "3", "4", "5"],
            index=0,
            key=f"metrics_{workflow_id}_{run_id}_rating",
        )

        feedback_text = st.text_area(
            "Optional non-confidential feedback (do not include customer, ticket, filename, vehicle program, or other sensitive data)",
            key=f"metrics_{workflow_id}_{run_id}_feedback_text",
        )

        submit_feedback = st.form_submit_button("Save impact feedback")

    if submit_feedback:
        payload = {
            "baseline_minutes": pre_run_answers.get("baseline_minutes"),
            "baseline_manual_touchpoints": pre_run_answers.get("baseline_manual_touchpoints"),
            "remaining_manual_touchpoints": None if remaining_skip else int(remaining_touchpoints),
            "user_reported_errors_prevented": int(error_count) if error_count is not None else None,
            "usefulness_rating": None if rating == "Skip" else int(rating),
            "non_confidential_feedback": feedback_text.strip() or None,
            "processing_seconds": float(processing_seconds),
        }
        tracker.save_workflow_feedback(workflow_id, run_id, payload)
        submitted.add(run_id)
        st.session_state[feedback_state_key] = submitted
        st.success("Impact feedback saved.")


def metrics_admin_enabled() -> bool:
    token = os.getenv("METRICS_ADMIN_TOKEN") or os.getenv("STREAMLIT_METRICS_ADMIN_TOKEN")
    if token:
        return True
    try:
        return bool(
            st.secrets.get("METRICS_ADMIN_TOKEN")
            or st.secrets.get("STREAMLIT_METRICS_ADMIN_TOKEN")
        )
    except Exception:
        return False
