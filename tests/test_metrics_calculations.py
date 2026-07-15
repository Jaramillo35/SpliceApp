from __future__ import annotations

from metrics.calculations import (
    manual_touchpoints_eliminated,
    time_saved_minutes,
    time_savings_percentage,
    to_minutes,
)


def test_to_minutes_handles_null_and_zero() -> None:
    assert to_minutes(None, None) is None
    assert to_minutes(0, 0) is None
    assert to_minutes(1, 30) == 90


def test_manual_touchpoints_eliminated_bounds_at_zero() -> None:
    assert manual_touchpoints_eliminated(10, 4) == 6
    assert manual_touchpoints_eliminated(2, 8) == 0
    assert manual_touchpoints_eliminated(None, 2) is None


def test_time_saved_minutes_null_and_computation() -> None:
    assert time_saved_minutes(None, 120) is None
    assert time_saved_minutes(60, None) is None
    assert round(time_saved_minutes(60, 600), 2) == 50.0


def test_time_savings_percentage_requires_positive_baseline() -> None:
    assert time_savings_percentage(None, 120) is None
    assert time_savings_percentage(0, 120) is None
    assert round(time_savings_percentage(120, 1800), 2) == 75.0
