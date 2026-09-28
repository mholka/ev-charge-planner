"""Tests for the rolling baseline."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.ev_charge_planner.baseline import RollingAverage

T0 = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)


def test_empty() -> None:
    assert RollingAverage(timedelta(minutes=30)).mean(T0) is None


def test_single_sample() -> None:
    avg = RollingAverage(timedelta(minutes=30))
    avg.add(T0, 400)
    assert avg.mean(T0) == 400
    assert avg.mean(T0 + timedelta(hours=2)) == 400


def test_time_weighted() -> None:
    avg = RollingAverage(timedelta(minutes=30))
    avg.add(T0 - timedelta(hours=1), 1000)  # value at window start
    avg.add(T0 + timedelta(minutes=10), 400)
    # window 08:00-08:30: 10 min at 1000, 20 min at 400
    assert avg.mean(T0 + timedelta(minutes=30)) == pytest.approx(
        (10 * 1000 + 20 * 400) / 30
    )


def test_old_samples_pruned() -> None:
    avg = RollingAverage(timedelta(minutes=30))
    avg.add(T0, 5000)
    avg.add(T0 + timedelta(minutes=1), 300)
    assert avg.mean(T0 + timedelta(hours=1)) == 300
    assert len(avg._samples) == 1


def test_out_of_order_ignored() -> None:
    avg = RollingAverage(timedelta(minutes=30))
    avg.add(T0, 300)
    avg.add(T0 - timedelta(minutes=5), 9000)
    assert avg.mean(T0 + timedelta(minutes=5)) == 300
