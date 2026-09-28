"""Tests for forecast adapters."""

from datetime import UTC, datetime, timedelta

from custom_components.ev_charge_planner.forecast import merge_slots, parse_solcast

T0 = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)


def test_parse_solcast_detailed_forecast() -> None:
    attrs = {
        "detailedForecast": [
            {"period_start": T0 + timedelta(minutes=30), "pv_estimate": 2.5},
            {"period_start": T0.isoformat(), "pv_estimate": 1.2, "pv_estimate10": 0.8},
        ]
    }
    slots = parse_solcast(attrs)
    assert [s.start for s in slots] == [T0, T0 + timedelta(minutes=30)]
    assert slots[0].end == T0 + timedelta(minutes=30)
    assert slots[1].end == T0 + timedelta(hours=1)
    assert [s.pv_w for s in slots] == [1200, 2500]


def test_parse_solcast_hourly_fallback_and_invalid_items() -> None:
    attrs = {
        "detailedHourly": [
            {"period_start": T0, "pv_estimate": 1},
            {"period_start": T0 + timedelta(hours=1), "pv_estimate": "bad"},
            {"period_start": "not a date", "pv_estimate": 1},
            {"period_start": "2026-06-01T10:00:00", "pv_estimate": 1},  # naive
            "garbage",
            {"period_start": T0 + timedelta(hours=2), "pv_estimate": -0.1},
        ]
    }
    slots = parse_solcast(attrs)
    assert [s.start for s in slots] == [T0, T0 + timedelta(hours=2)]
    assert slots[0].end == T0 + timedelta(hours=2)  # inferred from the only diff
    assert slots[1].pv_w == 0


def test_parse_solcast_missing() -> None:
    assert parse_solcast({}) == []
    assert parse_solcast({"detailedForecast": "x"}) == []


def test_merge_slots() -> None:
    today = parse_solcast(
        {"detailedForecast": [{"period_start": T0, "pv_estimate": 1}]}
    )
    tomorrow = parse_solcast(
        {
            "detailedForecast": [
                {"period_start": T0 + timedelta(days=1), "pv_estimate": 2},
                {"period_start": T0, "pv_estimate": 9},
            ]
        }
    )
    merged = merge_slots(today, tomorrow)
    assert [s.pv_w for s in merged] == [1000, 2000]
