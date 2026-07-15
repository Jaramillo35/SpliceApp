from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Protocol


LOGGER = logging.getLogger(__name__)


class MetricsStorage(Protocol):
    def create_workflow_run(self, payload: dict[str, Any]) -> None: ...

    def update_workflow_run(self, run_id: str, payload: dict[str, Any]) -> None: ...

    def create_workflow_feedback(self, payload: dict[str, Any]) -> None: ...

    def get_latest_baseline(self, anonymous_session_id: str, workflow_id: str) -> dict[str, Any] | None: ...

    def fetch_dashboard_metrics(self, weeks: int = 12) -> dict[str, list[dict[str, Any]]]: ...

    def is_available(self) -> bool: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _week_start(value: datetime) -> datetime:
    normalized = value.astimezone(timezone.utc)
    return (normalized - timedelta(days=normalized.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(mean(values))


class JsonMetricsStorage:
    def __init__(self, file_path: str | os.PathLike[str]) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.file_path.exists():
            self.file_path.write_text(
                json.dumps({"workflow_runs": [], "workflow_feedback": []}, indent=2),
                encoding="utf-8",
            )

    def _load(self) -> dict[str, Any]:
        with self._lock:
            try:
                payload = json.loads(self.file_path.read_text(encoding="utf-8"))
            except Exception:
                payload = {"workflow_runs": [], "workflow_feedback": []}
            payload.setdefault("workflow_runs", [])
            payload.setdefault("workflow_feedback", [])
            return payload

    def _save(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = {}
        for key, value in payload.items():
            if isinstance(value, datetime):
                normalized[key] = value.astimezone(timezone.utc).isoformat()
            else:
                normalized[key] = value
        return normalized

    def create_workflow_run(self, payload: dict[str, Any]) -> None:
        data = self._load()
        run_id = payload.get("id")
        if run_id and any(existing.get("id") == run_id for existing in data["workflow_runs"]):
            return
        data["workflow_runs"].append(self._normalize_payload(payload))
        self._save(data)

    def update_workflow_run(self, run_id: str, payload: dict[str, Any]) -> None:
        if not payload:
            return
        data = self._load()
        normalized = self._normalize_payload(payload)
        for row in data["workflow_runs"]:
            if row.get("id") == run_id:
                row.update(normalized)
                self._save(data)
                return

    def create_workflow_feedback(self, payload: dict[str, Any]) -> None:
        data = self._load()
        workflow_run_id = payload.get("workflow_run_id")
        if workflow_run_id and any(existing.get("workflow_run_id") == workflow_run_id for existing in data["workflow_feedback"]):
            return
        data["workflow_feedback"].append(self._normalize_payload(payload))
        self._save(data)

    def get_latest_baseline(self, anonymous_session_id: str, workflow_id: str) -> dict[str, Any] | None:
        data = self._load()
        candidates = [
            row
            for row in data["workflow_feedback"]
            if row.get("anonymous_session_id") == anonymous_session_id
            and row.get("workflow_id") == workflow_id
            and (row.get("baseline_minutes") is not None or row.get("baseline_manual_touchpoints") is not None)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda row: _parse_datetime(row.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        latest = candidates[0]
        return {
            "baseline_minutes": latest.get("baseline_minutes"),
            "baseline_manual_touchpoints": latest.get("baseline_manual_touchpoints"),
        }

    def fetch_dashboard_metrics(self, weeks: int = 12) -> dict[str, list[dict[str, Any]]]:
        cutoff = _utc_now() - timedelta(weeks=weeks)
        data = self._load()

        runs = []
        for row in data["workflow_runs"]:
            completed_at = _parse_datetime(row.get("completed_at"))
            if completed_at is None or completed_at < cutoff:
                continue
            row_copy = dict(row)
            row_copy["_completed_at"] = completed_at
            runs.append(row_copy)

        completed_runs = [row for row in runs if row.get("status") == "completed"]

        weekly_workflows_map: dict[tuple[str, str], int] = {}
        for row in completed_runs:
            week = _week_start(row["_completed_at"]).date().isoformat()
            key = (week, str(row.get("workflow_id") or "unknown"))
            weekly_workflows_map[key] = weekly_workflows_map.get(key, 0) + 1

        weekly_workflows = [
            {"week_start": key[0], "workflow_id": key[1], "completed_runs": value}
            for key, value in sorted(weekly_workflows_map.items())
        ]

        weekly_sessions_map: dict[str, set[str]] = {}
        for row in completed_runs:
            week = _week_start(row["_completed_at"]).date().isoformat()
            weekly_sessions_map.setdefault(week, set()).add(str(row.get("anonymous_session_id") or ""))

        weekly_sessions = [
            {"week_start": week, "unique_sessions": len(session_ids)}
            for week, session_ids in sorted(weekly_sessions_map.items())
        ]

        feedback_by_run = {
            row.get("workflow_run_id"): row
            for row in data["workflow_feedback"]
            if _parse_datetime(row.get("created_at")) is not None
        }

        processing_values = [
            float(row["processing_seconds"])
            for row in completed_runs
            if row.get("processing_seconds") is not None
        ]
        rows_processed_values = [
            float(row["rows_processed"])
            for row in completed_runs
            if row.get("rows_processed") is not None
        ]

        baseline_values: list[float] = []
        saved_minutes_values: list[float] = []
        savings_percentage_values: list[float] = []
        manual_touchpoints_total = 0

        comparable_count = 0
        for row in completed_runs:
            feedback = feedback_by_run.get(row.get("id"))
            if feedback is None:
                continue
            if feedback.get("baseline_minutes") is not None:
                baseline_values.append(float(feedback["baseline_minutes"]))
            if feedback.get("time_saved_minutes") is not None:
                saved_minutes_values.append(float(feedback["time_saved_minutes"]))
            if feedback.get("time_savings_percentage") is not None:
                savings_percentage_values.append(float(feedback["time_savings_percentage"]))
            if feedback.get("manual_touchpoints_eliminated") is not None:
                manual_touchpoints_total += int(feedback["manual_touchpoints_eliminated"])
            if feedback.get("baseline_minutes") is not None and feedback.get("time_savings_percentage") is not None:
                comparable_count += 1

        summary = [
            {
                "completed_runs": len(completed_runs),
                "avg_processing_seconds": _mean_or_none(processing_values),
                "median_processing_seconds": _median_or_none(processing_values),
                "median_rows_processed": _median_or_none(rows_processed_values),
                "total_circuits": int(sum(int(row.get("circuits_processed") or 0) for row in completed_runs)),
                "total_harness_variants": int(sum(int(row.get("harness_variants_processed") or 0) for row in completed_runs)),
                "median_baseline_minutes": _median_or_none(baseline_values),
                "median_time_saved_minutes": _median_or_none(saved_minutes_values),
                "median_time_savings_percentage": _median_or_none(savings_percentage_values),
                "manual_touchpoints_eliminated": manual_touchpoints_total,
                "automatic_validation_errors": int(sum(int(row.get("automatic_validation_errors") or 0) for row in completed_runs)),
                "comparable_time_savings_ratio": (
                    (float(comparable_count) / float(len(completed_runs))) if completed_runs else None
                ),
            }
        ]

        return {
            "weekly_workflows": weekly_workflows,
            "weekly_unique_sessions": weekly_sessions,
            "summary": summary,
        }

    def is_available(self) -> bool:
        return True


class NoopMetricsStorage:
    def __init__(self) -> None:
        self._warned = False

    def _warn_once(self) -> None:
        if not self._warned:
            LOGGER.warning("Metrics storage is not configured; metrics are not being persisted.")
            self._warned = True

    def create_workflow_run(self, payload: dict[str, Any]) -> None:
        self._warn_once()

    def update_workflow_run(self, run_id: str, payload: dict[str, Any]) -> None:
        self._warn_once()

    def create_workflow_feedback(self, payload: dict[str, Any]) -> None:
        self._warn_once()

    def get_latest_baseline(self, anonymous_session_id: str, workflow_id: str) -> dict[str, Any] | None:
        self._warn_once()
        return None

    def fetch_dashboard_metrics(self, weeks: int = 12) -> dict[str, list[dict[str, Any]]]:
        self._warn_once()
        return {
            "weekly_workflows": [],
            "weekly_unique_sessions": [],
            "summary": [],
        }

    def is_available(self) -> bool:
        return False


def build_metrics_storage() -> MetricsStorage:
    json_path = os.getenv("METRICS_JSON_PATH")
    if not json_path:
        json_path = str(Path(__file__).resolve().parents[1] / "data" / "impact_metrics.json")

    try:
        return JsonMetricsStorage(json_path)
    except Exception as exc:  # pragma: no cover
        LOGGER.warning("Failed to initialize JSON metrics storage (%s): %s", json_path, exc)
        return NoopMetricsStorage()
