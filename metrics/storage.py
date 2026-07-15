from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Protocol


LOGGER = logging.getLogger(__name__)


class MetricsStorage(Protocol):
    def create_workflow_run(self, payload: dict[str, Any]) -> None: ...

    def update_workflow_run(self, run_id: str, payload: dict[str, Any]) -> None: ...

    def create_workflow_feedback(self, payload: dict[str, Any]) -> None: ...

    def get_latest_baseline(self, anonymous_session_id: str, workflow_id: str) -> dict[str, Any] | None: ...

    def fetch_dashboard_metrics(self, weeks: int = 12) -> dict[str, list[dict[str, Any]]]: ...

    def is_available(self) -> bool: ...


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


class PostgresMetricsStorage:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        try:
            import psycopg  # noqa: F401
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required for PostgreSQL metrics storage") from exc

    @contextmanager
    def _connect(self):
        import psycopg

        conn = psycopg.connect(self._dsn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_workflow_run(self, payload: dict[str, Any]) -> None:
        query = """
        INSERT INTO workflow_runs (
            id,
            anonymous_user_id,
            anonymous_session_id,
            workflow_id,
            workflow_version,
            started_at,
            completed_at,
            status,
            processing_seconds,
            input_file_count,
            output_file_count,
            rows_read,
            rows_processed,
            circuits_processed,
            harness_variants_processed,
            automatic_validation_errors,
            automatic_validation_warnings,
            automatic_validation_failures,
            output_generated,
            failure_category,
            created_at
        ) VALUES (
            %(id)s,
            %(anonymous_user_id)s,
            %(anonymous_session_id)s,
            %(workflow_id)s,
            %(workflow_version)s,
            %(started_at)s,
            %(completed_at)s,
            %(status)s,
            %(processing_seconds)s,
            %(input_file_count)s,
            %(output_file_count)s,
            %(rows_read)s,
            %(rows_processed)s,
            %(circuits_processed)s,
            %(harness_variants_processed)s,
            %(automatic_validation_errors)s,
            %(automatic_validation_warnings)s,
            %(automatic_validation_failures)s,
            %(output_generated)s,
            %(failure_category)s,
            %(created_at)s
        )
        ON CONFLICT (id) DO NOTHING
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, payload)

    def update_workflow_run(self, run_id: str, payload: dict[str, Any]) -> None:
        if not payload:
            return
        assignments = ", ".join(f"{key} = %({key})s" for key in payload.keys())
        query = f"UPDATE workflow_runs SET {assignments} WHERE id = %(run_id)s"
        params = dict(payload)
        params["run_id"] = run_id
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)

    def create_workflow_feedback(self, payload: dict[str, Any]) -> None:
        query = """
        INSERT INTO workflow_feedback (
            id,
            workflow_run_id,
            workflow_id,
            anonymous_session_id,
            baseline_minutes,
            baseline_manual_touchpoints,
            remaining_manual_touchpoints,
            manual_touchpoints_eliminated,
            user_reported_errors_prevented,
            usefulness_rating,
            non_confidential_feedback,
            time_saved_minutes,
            time_savings_percentage,
            created_at
        ) VALUES (
            %(id)s,
            %(workflow_run_id)s,
            %(workflow_id)s,
            %(anonymous_session_id)s,
            %(baseline_minutes)s,
            %(baseline_manual_touchpoints)s,
            %(remaining_manual_touchpoints)s,
            %(manual_touchpoints_eliminated)s,
            %(user_reported_errors_prevented)s,
            %(usefulness_rating)s,
            %(non_confidential_feedback)s,
            %(time_saved_minutes)s,
            %(time_savings_percentage)s,
            %(created_at)s
        )
        ON CONFLICT (workflow_run_id) DO NOTHING
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, payload)

    def get_latest_baseline(self, anonymous_session_id: str, workflow_id: str) -> dict[str, Any] | None:
        query = """
        SELECT baseline_minutes, baseline_manual_touchpoints
        FROM workflow_feedback
        WHERE anonymous_session_id = %s
          AND workflow_id = %s
          AND (baseline_minutes IS NOT NULL OR baseline_manual_touchpoints IS NOT NULL)
        ORDER BY created_at DESC
        LIMIT 1
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (anonymous_session_id, workflow_id))
                row = cur.fetchone()
        if row is None:
            return None
        return {
            "baseline_minutes": row[0],
            "baseline_manual_touchpoints": row[1],
        }

    def fetch_dashboard_metrics(self, weeks: int = 12) -> dict[str, list[dict[str, Any]]]:
        weekly_workflows_query = """
        SELECT date_trunc('week', completed_at)::date AS week_start,
               workflow_id,
               COUNT(*) AS completed_runs
        FROM workflow_runs
        WHERE status = 'completed'
          AND completed_at >= NOW() - (%s || ' weeks')::interval
        GROUP BY 1, 2
        ORDER BY 1, 2
        """

        weekly_sessions_query = """
        SELECT date_trunc('week', completed_at)::date AS week_start,
               COUNT(DISTINCT anonymous_session_id) AS unique_sessions
        FROM workflow_runs
        WHERE status = 'completed'
          AND completed_at >= NOW() - (%s || ' weeks')::interval
        GROUP BY 1
        ORDER BY 1
        """

        summary_query = """
        SELECT
            COUNT(*) FILTER (WHERE wr.status = 'completed') AS completed_runs,
            AVG(wr.processing_seconds) FILTER (WHERE wr.status = 'completed') AS avg_processing_seconds,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY wr.processing_seconds)
                FILTER (WHERE wr.status = 'completed') AS median_processing_seconds,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY wr.rows_processed)
                FILTER (WHERE wr.status = 'completed' AND wr.rows_processed IS NOT NULL) AS median_rows_processed,
            COALESCE(SUM(wr.circuits_processed), 0) AS total_circuits,
            COALESCE(SUM(wr.harness_variants_processed), 0) AS total_harness_variants,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY wf.baseline_minutes)
                FILTER (WHERE wf.baseline_minutes IS NOT NULL) AS median_baseline_minutes,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY wf.time_saved_minutes)
                FILTER (WHERE wf.time_saved_minutes IS NOT NULL) AS median_time_saved_minutes,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY wf.time_savings_percentage)
                FILTER (WHERE wf.time_savings_percentage IS NOT NULL) AS median_time_savings_percentage,
            COALESCE(SUM(wf.manual_touchpoints_eliminated), 0) AS manual_touchpoints_eliminated,
            COALESCE(SUM(wr.automatic_validation_errors), 0) AS automatic_validation_errors,
            CASE
                WHEN COUNT(*) FILTER (WHERE wr.status = 'completed') = 0 THEN NULL
                ELSE (
                    COUNT(*) FILTER (
                        WHERE wr.status = 'completed'
                          AND wf.baseline_minutes IS NOT NULL
                          AND wf.time_savings_percentage IS NOT NULL
                    )::float
                    / COUNT(*) FILTER (WHERE wr.status = 'completed')::float
                )
            END AS comparable_time_savings_ratio
        FROM workflow_runs wr
        LEFT JOIN workflow_feedback wf ON wf.workflow_run_id = wr.id
        WHERE wr.completed_at >= NOW() - (%s || ' weeks')::interval
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(weekly_workflows_query, (weeks,))
                weekly_workflows_rows = cur.fetchall()

                cur.execute(weekly_sessions_query, (weeks,))
                weekly_sessions_rows = cur.fetchall()

                cur.execute(summary_query, (weeks,))
                summary_row = cur.fetchone()

        weekly_workflows = [
            {
                "week_start": row[0],
                "workflow_id": row[1],
                "completed_runs": row[2],
            }
            for row in weekly_workflows_rows
        ]
        weekly_sessions = [
            {
                "week_start": row[0],
                "unique_sessions": row[1],
            }
            for row in weekly_sessions_rows
        ]
        summary = []
        if summary_row is not None:
            summary.append(
                {
                    "completed_runs": summary_row[0],
                    "avg_processing_seconds": summary_row[1],
                    "median_processing_seconds": summary_row[2],
                    "median_rows_processed": summary_row[3],
                    "total_circuits": summary_row[4],
                    "total_harness_variants": summary_row[5],
                    "median_baseline_minutes": summary_row[6],
                    "median_time_saved_minutes": summary_row[7],
                    "median_time_savings_percentage": summary_row[8],
                    "manual_touchpoints_eliminated": summary_row[9],
                    "automatic_validation_errors": summary_row[10],
                    "comparable_time_savings_ratio": summary_row[11],
                }
            )

        return {
            "weekly_workflows": weekly_workflows,
            "weekly_unique_sessions": weekly_sessions,
            "summary": summary,
        }

    def is_available(self) -> bool:
        return True


def build_metrics_storage() -> MetricsStorage:
    dsn = os.getenv("METRICS_DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        try:
            import streamlit as st

            dsn = (
                st.secrets.get("METRICS_DATABASE_URL")
                or st.secrets.get("SUPABASE_DB_URL")
                or st.secrets.get("DATABASE_URL")
            )
        except Exception:
            dsn = None
    if not dsn:
        return NoopMetricsStorage()

    try:
        return PostgresMetricsStorage(dsn=dsn)
    except Exception as exc:  # pragma: no cover
        LOGGER.warning("Failed to initialize PostgreSQL metrics storage: %s", exc)
        return NoopMetricsStorage()
