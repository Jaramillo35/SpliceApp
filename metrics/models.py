from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class WorkflowRunRecord:
    id: str
    anonymous_user_id: str | None
    anonymous_session_id: str
    workflow_id: str
    workflow_version: str | None
    started_at: datetime
    completed_at: datetime | None
    status: str
    processing_seconds: float | None
    input_file_count: int | None
    output_file_count: int | None
    rows_read: int | None
    rows_processed: int | None
    circuits_processed: int | None
    harness_variants_processed: int | None
    automatic_validation_errors: int | None
    automatic_validation_warnings: int | None
    automatic_validation_failures: int | None
    output_generated: bool | None
    failure_category: str | None
    created_at: datetime


@dataclass
class WorkflowFeedbackRecord:
    id: str
    workflow_run_id: str
    workflow_id: str
    anonymous_session_id: str
    baseline_minutes: int | None
    baseline_manual_touchpoints: int | None
    remaining_manual_touchpoints: int | None
    manual_touchpoints_eliminated: int | None
    user_reported_errors_prevented: int | None
    usefulness_rating: int | None
    non_confidential_feedback: str | None
    time_saved_minutes: float | None
    time_savings_percentage: float | None
    created_at: datetime
