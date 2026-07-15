from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from .calculations import (
    clamp_optional_count,
    manual_touchpoints_eliminated,
    time_saved_minutes,
    time_savings_percentage,
)
from .storage import MetricsStorage


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_session_id() -> str:
    session_key = "metrics_anonymous_session_id"
    if session_key not in st.session_state:
        st.session_state[session_key] = str(uuid.uuid4())
    return st.session_state[session_key]


def _get_workflow_version() -> str | None:
    return (
        os.getenv("GIT_COMMIT_SHA")
        or os.getenv("VERCEL_GIT_COMMIT_SHA")
        or os.getenv("COMMIT_SHA")
    )


def _categorize_failure(exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError):
        return "file_not_found"
    if isinstance(exc, PermissionError):
        return "permission_error"
    if isinstance(exc, ValueError):
        return "validation_error"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "runtime_error"


@dataclass
class WorkflowRunContext:
    tracker: "MetricsTracker"
    workflow_id: str
    event_key: str
    input_file_count: int | None = None
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = field(default_factory=_utc_now)
    _started_monotonic: float = field(default_factory=time.monotonic)
    _completed: bool = False
    _metrics: dict[str, Any] = field(default_factory=dict)

    def __enter__(self) -> "WorkflowRunContext":
        payload = {
            "id": self.run_id,
            "anonymous_user_id": None,
            "anonymous_session_id": self.tracker.anonymous_session_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.tracker.workflow_version,
            "started_at": self.started_at,
            "completed_at": None,
            "status": "started",
            "processing_seconds": None,
            "input_file_count": self.input_file_count,
            "output_file_count": None,
            "rows_read": None,
            "rows_processed": None,
            "circuits_processed": None,
            "harness_variants_processed": None,
            "automatic_validation_errors": None,
            "automatic_validation_warnings": None,
            "automatic_validation_failures": None,
            "output_generated": None,
            "failure_category": None,
            "created_at": self.started_at,
        }
        self.tracker._safe_storage_call("create_workflow_run", payload)
        self.tracker._set_active_run(self.workflow_id, self.run_id)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.fail(exc)
            return False
        if not self._completed:
            self.abandon()
        return False

    def record_counts(
        self,
        *,
        rows_read: int | None = None,
        rows_processed: int | None = None,
        circuits_processed: int | None = None,
        harness_variants_processed: int | None = None,
        input_file_count: int | None = None,
        output_file_count: int | None = None,
    ) -> None:
        if rows_read is not None:
            self._metrics["rows_read"] = clamp_optional_count(rows_read)
        if rows_processed is not None:
            self._metrics["rows_processed"] = clamp_optional_count(rows_processed)
        if circuits_processed is not None:
            self._metrics["circuits_processed"] = clamp_optional_count(circuits_processed)
        if harness_variants_processed is not None:
            self._metrics["harness_variants_processed"] = clamp_optional_count(harness_variants_processed)
        if input_file_count is not None:
            self._metrics["input_file_count"] = clamp_optional_count(input_file_count)
        if output_file_count is not None:
            self._metrics["output_file_count"] = clamp_optional_count(output_file_count)

    def record_validation_results(
        self,
        *,
        automatic_validation_errors: int | None = None,
        automatic_validation_warnings: int | None = None,
        automatic_validation_failures: int | None = None,
    ) -> None:
        if automatic_validation_errors is not None:
            self._metrics["automatic_validation_errors"] = clamp_optional_count(automatic_validation_errors)
        if automatic_validation_warnings is not None:
            self._metrics["automatic_validation_warnings"] = clamp_optional_count(automatic_validation_warnings)
        if automatic_validation_failures is not None:
            self._metrics["automatic_validation_failures"] = clamp_optional_count(automatic_validation_failures)

    def complete(self, *, output_generated: bool, output_file_count: int | None = None) -> None:
        if self._completed:
            return
        completed_at = _utc_now()
        processing_seconds = max(time.monotonic() - self._started_monotonic, 0.0)
        payload = {
            **self._metrics,
            "completed_at": completed_at,
            "status": "completed",
            "processing_seconds": processing_seconds,
            "output_generated": bool(output_generated),
            "failure_category": None,
        }
        if output_file_count is not None:
            payload["output_file_count"] = clamp_optional_count(output_file_count)
        self.tracker._safe_storage_call("update_workflow_run", self.run_id, payload)
        self.tracker._mark_event_completed(self.event_key)
        self.tracker._set_last_completed_run(self.workflow_id, self.run_id, processing_seconds)
        self._completed = True

    def fail(self, exc: BaseException) -> None:
        if self._completed:
            return
        completed_at = _utc_now()
        processing_seconds = max(time.monotonic() - self._started_monotonic, 0.0)
        payload = {
            **self._metrics,
            "completed_at": completed_at,
            "status": "failed",
            "processing_seconds": processing_seconds,
            "output_generated": False,
            "failure_category": _categorize_failure(exc),
        }
        self.tracker._safe_storage_call("update_workflow_run", self.run_id, payload)
        self.tracker._mark_event_completed(self.event_key)
        self._completed = True

    def abandon(self) -> None:
        if self._completed:
            return
        payload = {
            **self._metrics,
            "completed_at": _utc_now(),
            "status": "abandoned",
            "processing_seconds": max(time.monotonic() - self._started_monotonic, 0.0),
            "output_generated": False,
            "failure_category": None,
        }
        self.tracker._safe_storage_call("update_workflow_run", self.run_id, payload)
        self.tracker._mark_event_completed(self.event_key)
        self._completed = True


class MetricsTracker:
    def __init__(self, storage: MetricsStorage) -> None:
        self.storage = storage
        self.anonymous_session_id = _get_session_id()
        self.workflow_version = _get_workflow_version()
        st.session_state.setdefault("metrics_completed_events", set())
        st.session_state.setdefault("metrics_active_runs", {})
        st.session_state.setdefault("metrics_last_completed_run", {})

    def _safe_storage_call(self, method_name: str, *args, **kwargs) -> Any | None:
        try:
            method = getattr(self.storage, method_name)
            return method(*args, **kwargs)
        except Exception:
            return None

    def _set_active_run(self, workflow_id: str, run_id: str) -> None:
        active = st.session_state.get("metrics_active_runs", {})
        active[workflow_id] = run_id
        st.session_state["metrics_active_runs"] = active

    def _mark_event_completed(self, event_key: str) -> None:
        completed = st.session_state.get("metrics_completed_events", set())
        completed.add(event_key)
        st.session_state["metrics_completed_events"] = completed

    def _set_last_completed_run(self, workflow_id: str, run_id: str, processing_seconds: float) -> None:
        payload = st.session_state.get("metrics_last_completed_run", {})
        payload[workflow_id] = {
            "run_id": run_id,
            "processing_seconds": processing_seconds,
        }
        st.session_state["metrics_last_completed_run"] = payload

    def should_track_event(self, event_key: str) -> bool:
        completed = st.session_state.get("metrics_completed_events", set())
        return event_key not in completed

    def track_workflow(
        self,
        workflow_id: str,
        *,
        event_key: str,
        input_file_count: int | None = None,
    ) -> WorkflowRunContext:
        return WorkflowRunContext(
            tracker=self,
            workflow_id=workflow_id,
            event_key=event_key,
            input_file_count=input_file_count,
        )

    def get_last_completed_run(self, workflow_id: str) -> dict[str, Any] | None:
        return st.session_state.get("metrics_last_completed_run", {}).get(workflow_id)

    def get_latest_baseline_prefill(self, workflow_id: str) -> dict[str, int | None]:
        session_key = f"metrics_baseline_prefill_{workflow_id}"
        if session_key in st.session_state:
            return st.session_state[session_key]

        latest = self._safe_storage_call(
            "get_latest_baseline",
            self.anonymous_session_id,
            workflow_id,
        )
        payload = {
            "baseline_minutes": (latest or {}).get("baseline_minutes"),
            "baseline_manual_touchpoints": (latest or {}).get("baseline_manual_touchpoints"),
        }
        st.session_state[session_key] = payload
        return payload

    def save_workflow_feedback(self, workflow_id: str, workflow_run_id: str, payload: dict[str, Any]) -> None:
        processing_seconds = payload.get("processing_seconds")
        baseline_minutes = payload.get("baseline_minutes")

        feedback_payload = {
            "id": str(uuid.uuid4()),
            "workflow_run_id": workflow_run_id,
            "workflow_id": workflow_id,
            "anonymous_session_id": self.anonymous_session_id,
            "baseline_minutes": baseline_minutes,
            "baseline_manual_touchpoints": payload.get("baseline_manual_touchpoints"),
            "remaining_manual_touchpoints": payload.get("remaining_manual_touchpoints"),
            "manual_touchpoints_eliminated": manual_touchpoints_eliminated(
                payload.get("baseline_manual_touchpoints"),
                payload.get("remaining_manual_touchpoints"),
            ),
            "user_reported_errors_prevented": payload.get("user_reported_errors_prevented"),
            "usefulness_rating": payload.get("usefulness_rating"),
            "non_confidential_feedback": payload.get("non_confidential_feedback"),
            "time_saved_minutes": time_saved_minutes(baseline_minutes, processing_seconds),
            "time_savings_percentage": time_savings_percentage(baseline_minutes, processing_seconds),
            "created_at": _utc_now(),
        }
        self._safe_storage_call("create_workflow_feedback", feedback_payload)

        prefill_key = f"metrics_baseline_prefill_{workflow_id}"
        st.session_state[prefill_key] = {
            "baseline_minutes": feedback_payload["baseline_minutes"],
            "baseline_manual_touchpoints": feedback_payload["baseline_manual_touchpoints"],
        }

    def metrics_storage_available(self) -> bool:
        try:
            return bool(self.storage.is_available())
        except Exception:
            return False
