from __future__ import annotations


def to_minutes(hours: int | None, minutes: int | None) -> int | None:
    if hours is None and minutes is None:
        return None
    safe_hours = max(int(hours or 0), 0)
    safe_minutes = max(int(minutes or 0), 0)
    total = safe_hours * 60 + safe_minutes
    return total if total > 0 else None


def manual_touchpoints_eliminated(
    baseline_manual_touchpoints: int | None,
    remaining_manual_touchpoints: int | None,
) -> int | None:
    if baseline_manual_touchpoints is None or remaining_manual_touchpoints is None:
        return None
    return max(int(baseline_manual_touchpoints) - int(remaining_manual_touchpoints), 0)


def time_saved_minutes(
    baseline_minutes: int | None,
    automated_processing_seconds: float | None,
) -> float | None:
    if baseline_minutes is None or automated_processing_seconds is None:
        return None
    automated_minutes = max(float(automated_processing_seconds), 0.0) / 60.0
    return max(float(baseline_minutes) - automated_minutes, 0.0)


def time_savings_percentage(
    baseline_minutes: int | None,
    automated_processing_seconds: float | None,
) -> float | None:
    if baseline_minutes is None or automated_processing_seconds is None:
        return None
    if baseline_minutes <= 0:
        return None
    automated_minutes = max(float(automated_processing_seconds), 0.0) / 60.0
    return ((float(baseline_minutes) - automated_minutes) / float(baseline_minutes)) * 100.0


def clamp_optional_count(value: int | None) -> int | None:
    if value is None:
        return None
    return max(int(value), 0)
