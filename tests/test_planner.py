"""Unit tests for the pure planner module."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.ev_charge_planner.planner import (
    ChargerParams,
    Slot,
    VehicleParams,
    deadline_plan,
    energy_needed_kwh,
    forecast_power_at,
    grid_eta,
    nowcast_factor,
    pv_energy_until,
    pv_eta,
    surplus_charge_power,
    trip_target_soc,
)

NOW = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
VEHICLE = VehicleParams(capacity_kwh=75, km_per_kwh=5, efficiency=0.9, reserve_pct=10)
CHARGER = ChargerParams(p_min_w=4100, p_max_w=11000)


def slots(*pv_w: float, start: datetime = NOW, minutes: int = 60) -> list[Slot]:
    step = timedelta(minutes=minutes)
    return [
        Slot(start + i * step, start + (i + 1) * step, p) for i, p in enumerate(pv_w)
    ]


def test_trip_target_soc() -> None:
    # 150 km round trip = 300 km / 5 km/kWh = 60 kWh = 80 % of 75 kWh, + 10 % reserve
    assert trip_target_soc(150, True, VEHICLE) == pytest.approx(90)
    assert trip_target_soc(150, False, VEHICLE) == pytest.approx(50)
    assert trip_target_soc(300, True, VEHICLE) > 100


def test_energy_needed() -> None:
    assert energy_needed_kwh(50, 80, VEHICLE) == pytest.approx(30 / 100 * 75 / 0.9)
    assert energy_needed_kwh(80, 80, VEHICLE) == 0
    assert energy_needed_kwh(90, 80, VEHICLE) == 0


def test_grid_eta() -> None:
    assert grid_eta(NOW, 11, CHARGER) == NOW + timedelta(hours=1)
    assert grid_eta(NOW, 0, CHARGER) == NOW


def test_grid_eta_matches_tesla_time_to_full() -> None:
    """Acceptance: within ±10 % of the car's own estimate below 80 % SoC.

    Tesla reports time_to_full ≈ battery kWh / (charger power × η). Our model is
    the same formula, so the ratio must be 1 for any SoC below the taper.
    """
    for soc in (10, 40, 70):
        energy = energy_needed_kwh(soc, 80, VEHICLE)
        ours = (grid_eta(NOW, energy, CHARGER) - NOW).total_seconds()
        tesla = (80 - soc) / 100 * 75 / (11 * 0.9) * 3600
        assert ours == pytest.approx(tesla, rel=0.10)


@pytest.mark.parametrize(
    ("surplus", "expected"),
    [(0, 0), (4099, 0), (4100, 4100), (6000, 6000), (15000, 11000), (-500, 0)],
)
def test_surplus_charge_power_p_min_threshold(surplus: float, expected: float) -> None:
    assert surplus_charge_power(surplus, CHARGER) == expected


def test_nowcast_factor() -> None:
    assert nowcast_factor(None, 5000) == 1.0
    assert nowcast_factor(3000, None) == 1.0
    assert nowcast_factor(3000, 50) == 1.0  # forecast ≈ 0: no correction
    assert nowcast_factor(2500, 5000) == 0.5
    assert nowcast_factor(0, 5000) == 0.3  # clamped
    assert nowcast_factor(50000, 5000) == 2.0  # clamped


def test_forecast_power_at() -> None:
    s = slots(1000, 2000)
    assert forecast_power_at(s, NOW + timedelta(minutes=90)) == 2000
    assert forecast_power_at(s, NOW + timedelta(hours=3)) is None


def test_pv_eta_soc_at_target() -> None:
    assert pv_eta(NOW, 0, [], 500, CHARGER) == NOW


def test_pv_eta_basic_interpolation() -> None:
    # 6500 W PV - 500 W baseline = 6 kW surplus; 9 kWh -> 1.5 h
    eta = pv_eta(NOW, 9, slots(6500, 6500, 6500), 500, CHARGER)
    assert eta == NOW + timedelta(hours=1.5)


def test_pv_eta_zero_surplus_unknown() -> None:
    assert pv_eta(NOW, 5, slots(0, 0, 0), 500, CHARGER) is None


def test_pv_eta_below_p_min_unknown() -> None:
    # 4500 - 500 = 4000 W < 4100 W minimum
    assert pv_eta(NOW, 5, slots(4500, 4500), 500, CHARGER) is None


def test_pv_eta_unreachable_in_horizon() -> None:
    # 2 h at 6 kW = 12 kWh < 20 kWh
    assert pv_eta(NOW, 20, slots(6500, 6500), 500, CHARGER) is None


def test_pv_eta_caps_at_p_max() -> None:
    eta = pv_eta(NOW, 11, slots(20000, 20000), 500, CHARGER)
    assert eta == NOW + timedelta(hours=1)


def test_pv_eta_forecast_gap_counts_as_zero() -> None:
    s = [
        Slot(NOW, NOW + timedelta(hours=1), 6500),
        # gap 11:00-13:00
        Slot(NOW + timedelta(hours=3), NOW + timedelta(hours=4), 6500),
    ]
    eta = pv_eta(NOW, 9, s, 500, CHARGER)
    assert eta == NOW + timedelta(hours=3, minutes=30)


def test_pv_eta_first_slot_partial_and_nowcast() -> None:
    now = NOW + timedelta(minutes=30)
    s = slots(6500, 6500)
    # Remaining 30 min of slot 1, then slot 2: 1.5 h at 6 kW = 9 kWh
    assert pv_eta(now, 9, s, 500, CHARGER) == NOW + timedelta(hours=2)
    # Nowcast halves the current slot (3250 - 500 < P_min), only slot 2 counts
    assert pv_eta(now, 6, s, 500, CHARGER, factor=0.5) == NOW + timedelta(hours=2)
    assert pv_eta(now, 9, s, 500, CHARGER, factor=0.5) is None


def test_pv_eta_ignores_past_slots() -> None:
    s = slots(20000, 0, start=NOW - timedelta(hours=1))
    assert pv_eta(NOW, 1, s, 500, CHARGER) is None


def test_pv_energy_until() -> None:
    s = slots(6500, 6500, 6500)
    assert pv_energy_until(
        NOW, NOW + timedelta(hours=2), s, 500, CHARGER
    ) == pytest.approx(12)
    assert pv_energy_until(NOW, NOW, s, 500, CHARGER) == 0


def test_deadline_nothing_needed() -> None:
    result = deadline_plan(NOW, NOW + timedelta(hours=5), 0, [], 500, CHARGER)
    assert result.grid_topup_kwh == 0
    assert result.latest_grid_start is None
    assert not result.at_risk


def test_deadline_pv_sufficient() -> None:
    result = deadline_plan(
        NOW, NOW + timedelta(hours=3), 10, slots(6500, 6500, 6500), 500, CHARGER
    )
    assert result.grid_topup_kwh == 0
    assert result.latest_grid_start is None
    assert not result.at_risk


def test_deadline_grid_only() -> None:
    # No PV: 22 kWh at 11 kW -> start 2 h before deadline
    deadline = NOW + timedelta(hours=8)
    result = deadline_plan(NOW, deadline, 22, [], 500, CHARGER)
    assert result.grid_topup_kwh == pytest.approx(22)
    assert abs(result.latest_grid_start - (deadline - timedelta(hours=2))) <= timedelta(
        minutes=1
    )
    assert not result.at_risk


def test_deadline_hybrid() -> None:
    # PV 6 kW for 4 h, deadline in 4 h, need 35 kWh.
    # pv(s) + 11 * (4 - s) = 35 with pv(s) = 6 s  ->  44 - 5 s = 35  ->  s = 1.8 h
    deadline = NOW + timedelta(hours=4)
    result = deadline_plan(
        NOW, deadline, 35, slots(6500, 6500, 6500, 6500), 500, CHARGER
    )
    assert abs(result.latest_grid_start - (NOW + timedelta(hours=1.8))) <= timedelta(
        minutes=1
    )
    assert result.grid_topup_kwh == pytest.approx(35 - 6 * 1.8, abs=0.2)
    assert not result.at_risk


def test_deadline_at_risk() -> None:
    deadline = NOW + timedelta(hours=1)
    result = deadline_plan(NOW, deadline, 20, [], 500, CHARGER)
    assert result.at_risk
    assert result.latest_grid_start == NOW
    assert result.grid_topup_kwh == 20


def test_deadline_in_past() -> None:
    result = deadline_plan(NOW, NOW - timedelta(hours=1), 5, [], 500, CHARGER)
    assert result.at_risk
    assert result.grid_topup_kwh == 5
