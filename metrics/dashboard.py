from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from .tracker import MetricsTracker


def render_metrics_dashboard(tracker: MetricsTracker) -> None:
    st.title("Workflow Impact Metrics Dashboard")

    admin_token = os.getenv("METRICS_ADMIN_TOKEN") or os.getenv("STREAMLIT_METRICS_ADMIN_TOKEN")
    if not admin_token:
        try:
            admin_token = st.secrets.get("METRICS_ADMIN_TOKEN") or st.secrets.get("STREAMLIT_METRICS_ADMIN_TOKEN")
        except Exception:
            admin_token = None
    if not admin_token:
        st.warning("Metrics dashboard is disabled. Configure METRICS_ADMIN_TOKEN to enable administrator access.")
        st.stop()

    provided = st.text_input("Administrator token", type="password")
    if provided != admin_token:
        st.info("Enter the administrator token to view aggregate metrics.")
        st.stop()

    if not tracker.metrics_storage_available():
        st.warning("Persistent metrics storage is not configured. Dashboard can only show data when PostgreSQL/Supabase is connected.")
        st.stop()

    weeks = st.slider("Lookback window (weeks)", min_value=4, max_value=52, value=12)
    payload = tracker._safe_storage_call("fetch_dashboard_metrics", weeks) or {}

    weekly_workflows = pd.DataFrame(payload.get("weekly_workflows", []))
    weekly_sessions = pd.DataFrame(payload.get("weekly_unique_sessions", []))
    summary = pd.DataFrame(payload.get("summary", []))

    if not summary.empty:
        row = summary.iloc[0]
        cols = st.columns(4)
        cols[0].metric("Completed workflows", int(row.get("completed_runs") or 0))
        cols[1].metric("Median processing (s)", f"{(row.get('median_processing_seconds') or 0):.2f}")
        cols[2].metric("Median rows processed", f"{(row.get('median_rows_processed') or 0):.0f}")
        ratio = row.get("comparable_time_savings_ratio")
        cols[3].metric(
            "Comparable time-savings coverage",
            "N/A" if ratio is None else f"{float(ratio) * 100:.1f}%",
        )

        secondary = st.columns(4)
        secondary[0].metric("Total circuits", int(row.get("total_circuits") or 0))
        secondary[1].metric("Total harness variants", int(row.get("total_harness_variants") or 0))
        secondary[2].metric("Median baseline (min)", f"{(row.get('median_baseline_minutes') or 0):.1f}")
        secondary[3].metric("Median time savings (%)", f"{(row.get('median_time_savings_percentage') or 0):.1f}")

        tertiary = st.columns(2)
        tertiary[0].metric("Manual touchpoints eliminated", int(row.get("manual_touchpoints_eliminated") or 0))
        tertiary[1].metric("Automatic validation errors", int(row.get("automatic_validation_errors") or 0))

    st.subheader("Completed workflows by week and workflow type")
    if weekly_workflows.empty:
        st.info("No completed workflow metrics found for the selected lookback window.")
    else:
        chart_df = weekly_workflows.copy()
        chart_df["week_start"] = pd.to_datetime(chart_df["week_start"])
        pivot = chart_df.pivot_table(
            index="week_start",
            columns="workflow_id",
            values="completed_runs",
            aggfunc="sum",
            fill_value=0,
        )
        st.line_chart(pivot)
        st.dataframe(chart_df, use_container_width=True)

    st.subheader("Approximate weekly unique sessions")
    if weekly_sessions.empty:
        st.info("No unique-session data found for the selected lookback window.")
    else:
        sessions_df = weekly_sessions.copy()
        sessions_df["week_start"] = pd.to_datetime(sessions_df["week_start"])
        st.line_chart(sessions_df.set_index("week_start")["unique_sessions"])
        st.dataframe(sessions_df, use_container_width=True)

    st.caption(
        "Privacy: this dashboard shows aggregate, non-confidential metrics only."
        " Weekly unique users are approximated by anonymous session identifiers unless authenticated identity is available."
    )
