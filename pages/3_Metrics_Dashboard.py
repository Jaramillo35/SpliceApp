from __future__ import annotations

from metrics.dashboard import render_metrics_dashboard
from metrics.storage import build_metrics_storage
from metrics.tracker import MetricsTracker


storage = build_metrics_storage()
tracker = MetricsTracker(storage)
render_metrics_dashboard(tracker)
