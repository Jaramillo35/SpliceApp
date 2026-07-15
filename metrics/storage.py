from __future__ import annotations

import base64
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Protocol
from urllib import error, parse, request

import streamlit as st


LOGGER = logging.getLogger(__name__)


def _get_streamlit_secret(*keys: str) -> str | None:
    try:
        github_secrets = st.secrets.get("github", {})
        for key in keys:
            if key in st.secrets and st.secrets[key]:
                return str(st.secrets[key])
            if isinstance(github_secrets, dict) and key in github_secrets and github_secrets[key]:
                return str(github_secrets[key])
            lower_key = key.lower()
            if isinstance(github_secrets, dict) and lower_key in github_secrets and github_secrets[lower_key]:
                return str(github_secrets[lower_key])
    except Exception:
        return None
    return None


def _get_config_value(env_key: str, *, default: str | None = None, secret_keys: tuple[str, ...] = ()) -> str | None:
    value = os.getenv(env_key)
    if value:
        return value
    lookup_keys = (env_key, *secret_keys)
    secret_value = _get_streamlit_secret(*lookup_keys)
    if secret_value:
        return secret_value
    return default


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
    def _sort_metric_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def sort_key(row: dict[str, Any]) -> tuple[str, str]:
            created_at = str(row.get("created_at") or row.get("started_at") or row.get("completed_at") or "")
            row_id = str(row.get("id") or row.get("workflow_run_id") or "")
            return (created_at, row_id)

        return sorted(rows, key=sort_key)

    @classmethod
    def _merge_rows(cls, existing: list[dict[str, Any]], incoming: list[dict[str, Any]], *, key_field: str) -> list[dict[str, Any]]:
        merged_by_key: dict[str, dict[str, Any]] = {}
        ordered_keys: list[str] = []

        for row in [*existing, *incoming]:
            key = str(row.get(key_field) or "")
            if not key:
                continue
            if key not in merged_by_key:
                ordered_keys.append(key)
            merged_by_key[key] = dict(row)

        merged_rows = [merged_by_key[key] for key in ordered_keys]
        return cls._sort_metric_rows(merged_rows)

    @classmethod
    def _merge_metrics_payload(cls, existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_runs": cls._merge_rows(
                existing.get("workflow_runs", []),
                incoming.get("workflow_runs", []),
                key_field="id",
            ),
            "workflow_feedback": cls._merge_rows(
                existing.get("workflow_feedback", []),
                incoming.get("workflow_feedback", []),
                key_field="workflow_run_id",
            ),
        }

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
                if row.get("status") in {"failed", "abandoned"}:
                    self.sync_to_github()
                return

    def create_workflow_feedback(self, payload: dict[str, Any]) -> None:
        data = self._load()
        workflow_run_id = payload.get("workflow_run_id")
        if workflow_run_id and any(existing.get("workflow_run_id") == workflow_run_id for existing in data["workflow_feedback"]):
            return
        data["workflow_feedback"].append(self._normalize_payload(payload))
        self._save(data)
        self.sync_to_github()

    def sync_to_github(
        self,
        *,
        repository: str | None = None,
        token: str | None = None,
        branch: str | None = None,
        file_path: str | None = None,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        repository = repository or _get_config_value(
            "GITHUB_REPOSITORY",
            secret_keys=("repository",),
        )
        token = token or _get_config_value(
            "GITHUB_TOKEN",
            secret_keys=("token",),
        )
        branch = branch or _get_config_value(
            "GITHUB_BRANCH",
            default="main",
            secret_keys=("branch",),
        )
        file_path = file_path or _get_config_value(
            "METRICS_GITHUB_PATH",
            default="data/impact_metrics.json",
            secret_keys=("metrics_path", "metrics_file_path"),
        )

        if not repository or not token:
            return {
                "ok": False,
                "message": "GitHub sync requires GITHUB_REPOSITORY and GITHUB_TOKEN (env vars or Streamlit secrets).",
            }

        encoded_path = parse.quote(file_path)
        url = f"https://api.github.com/repos/{repository}/contents/{encoded_path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }

        for attempt in range(max_attempts):
            remote_payload = {"workflow_runs": [], "workflow_feedback": []}
            sha: str | None = None

            try:
                existing_req = request.Request(url, headers=headers, method="GET")
                with request.urlopen(existing_req) as response:
                    existing = json.loads(response.read().decode("utf-8"))
                sha = existing.get("sha")
                raw_content = existing.get("content") or ""
                decoded = base64.b64decode(raw_content).decode("utf-8") if raw_content else "{}"
                loaded = json.loads(decoded) or {}
                if isinstance(loaded, dict):
                    remote_payload = {
                        "workflow_runs": loaded.get("workflow_runs", []),
                        "workflow_feedback": loaded.get("workflow_feedback", []),
                    }
            except error.HTTPError as exc:
                if exc.code != 404:
                    return {"ok": False, "message": f"GitHub lookup failed: {exc}"}
            except Exception as exc:
                return {"ok": False, "message": f"GitHub lookup failed: {exc}"}

            merged_payload = self._merge_metrics_payload(remote_payload, self._load())
            upload_payload = {
                "message": "Update automated impact metrics",
                "content": base64.b64encode(
                    json.dumps(merged_payload, indent=2, ensure_ascii=False).encode("utf-8")
                ).decode("utf-8"),
                "branch": branch,
            }
            if sha:
                upload_payload["sha"] = sha

            put_req = request.Request(
                url,
                data=json.dumps(upload_payload).encode("utf-8"),
                headers=headers,
                method="PUT",
            )
            try:
                with request.urlopen(put_req) as response:
                    response_body = json.loads(response.read().decode("utf-8"))
                self._save(merged_payload)
                return {
                    "ok": True,
                    "message": f"Metrics synced to {repository}/{file_path}",
                    "html_url": response_body.get("content", {}).get("html_url"),
                }
            except error.HTTPError as exc:
                if exc.code in {409, 422} and attempt + 1 < max_attempts:
                    continue
                return {"ok": False, "message": f"GitHub update failed: {exc}"}
            except Exception as exc:
                return {"ok": False, "message": f"GitHub update failed: {exc}"}

        return {"ok": False, "message": "GitHub update failed after multiple attempts."}

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
