from __future__ import annotations

import streamlit as st

from metrics.storage import NoopMetricsStorage
from metrics.tracker import MetricsTracker


class InMemoryStorage:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}
        self.feedback: list[dict] = []

    def create_workflow_run(self, payload):
        self.runs[payload["id"]] = dict(payload)

    def update_workflow_run(self, run_id, payload):
        self.runs[run_id].update(payload)

    def create_workflow_feedback(self, payload):
        self.feedback.append(dict(payload))

    def get_latest_baseline(self, anonymous_session_id, workflow_id):
        return None

    def fetch_dashboard_metrics(self, weeks=12):
        return {"weekly_workflows": [], "weekly_unique_sessions": [], "summary": []}

    def is_available(self):
        return True


def test_tracker_records_successful_workflow_completion() -> None:
    st.session_state.clear()
    storage = InMemoryStorage()
    tracker = MetricsTracker(storage)

    event_key = "unit-success-1"
    with tracker.track_workflow("splice_generation", event_key=event_key, input_file_count=1) as run:
        run.record_counts(rows_read=10, rows_processed=8, circuits_processed=3)
        run.record_validation_results(automatic_validation_errors=0, automatic_validation_warnings=1)
        run.complete(output_generated=True, output_file_count=1)

    assert tracker.should_track_event(event_key) is False
    completed = tracker.get_last_completed_run("splice_generation")
    assert completed is not None
    stored_run = storage.runs[completed["run_id"]]
    assert stored_run["status"] == "completed"
    assert stored_run["output_generated"] is True


def test_tracker_records_failed_workflow_without_stacktrace() -> None:
    st.session_state.clear()
    storage = InMemoryStorage()
    tracker = MetricsTracker(storage)

    event_key = "unit-fail-1"
    try:
        with tracker.track_workflow("dtx_compare_report", event_key=event_key, input_file_count=2):
            raise ValueError("file abc.xlsx missing required column")
    except ValueError:
        pass

    run_id = st.session_state["metrics_active_runs"]["dtx_compare_report"]
    stored_run = storage.runs[run_id]
    assert stored_run["status"] == "failed"
    assert stored_run["failure_category"] == "validation_error"
    assert "xlsx" not in str(stored_run)


def test_tracker_feedback_calculation_and_storage() -> None:
    st.session_state.clear()
    storage = InMemoryStorage()
    tracker = MetricsTracker(storage)

    event_key = "unit-feedback-1"
    with tracker.track_workflow("vbom_risk_matrix", event_key=event_key, input_file_count=3) as run:
        run.complete(output_generated=True, output_file_count=4)

    run = tracker.get_last_completed_run("vbom_risk_matrix")
    assert run is not None

    tracker.save_workflow_feedback(
        "vbom_risk_matrix",
        run["run_id"],
        {
            "baseline_minutes": 120,
            "baseline_manual_touchpoints": 12,
            "remaining_manual_touchpoints": 3,
            "user_reported_errors_prevented": 2,
            "usefulness_rating": 5,
            "non_confidential_feedback": "Helpful output validation.",
            "processing_seconds": 600.0,
        },
    )

    assert len(storage.feedback) == 1
    saved = storage.feedback[0]
    assert saved["manual_touchpoints_eliminated"] == 9
    assert round(saved["time_saved_minutes"], 2) == 110.0
    assert round(saved["time_savings_percentage"], 2) == 91.67


def test_storage_unavailability_never_blocks() -> None:
    st.session_state.clear()
    tracker = MetricsTracker(NoopMetricsStorage())

    with tracker.track_workflow("create_secr", event_key="noop-event", input_file_count=1) as run:
        run.record_counts(rows_read=1)
        run.complete(output_generated=True, output_file_count=1)

    assert tracker.get_last_completed_run("create_secr") is not None


def test_should_track_event_blocks_duplicates_after_completion() -> None:
    st.session_state.clear()
    storage = InMemoryStorage()
    tracker = MetricsTracker(storage)

    event_key = "rerun-duplicate-event"
    assert tracker.should_track_event(event_key) is True

    with tracker.track_workflow("dtcr_matching_report", event_key=event_key, input_file_count=2) as run:
        run.complete(output_generated=True, output_file_count=1)

    assert tracker.should_track_event(event_key) is False
