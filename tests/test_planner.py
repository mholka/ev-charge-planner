"""Unit tests for the pure planner module."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.ev_charge_planner.planner import (
    LIVE_PV_HOLD,
    PV_PHASE_AFTER,
    PV_PHASE_BEFORE,
    PV_PHASE_PAUSED,
    PV_PHASE_PRODUCING,
    ChargerParams,
    PvChargeTime,
    Slot,
    VehicleParams,
    deadline_plan,
    energy_needed_kwh,
    forecast_power_at,
    grid_eta,
    nowcast_factor,
    pv_charge_time,
    pv_energy_until,
    pv_eta,
    pv_phase,
    pv_projection,
    seasonal_km_per_kwh,
    surplus_charge_power,
    trip_energy_kwh,
    trip_target_soc,
    with_live_pv,
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


def test_battery_health_scales_usable_capacity() -> None:
    worn = VehicleParams(
        capacity_kwh=60, km_per_kwh=5, efficiency=0.9, reserve_pct=10, health_pct=95
    )
    assert worn.usable_kwh == pytest.approx(57)
    # Full charge from 0 %: 57 kWh into the battery, 57 / 0.9 from the wallbox.
    assert energy_needed_kwh(0, 100, worn) == pytest.approx(63.33, abs=0.01)
    # 57 km = 11.4 kWh = 20 % of 57 kWh, + 10 % minimum battery level
    assert trip_target_soc(57, False, worn) == pytest.approx(30)
    # The trip itself uses the same energy whatever the battery health.
    assert trip_energy_kwh(57, False, worn) == pytest.approx(11.4 / 0.9)


def test_trip_energy() -> None:
    # 150 km round trip = 300 km / 5 km/kWh = 60 kWh at the battery, / 0.9 losses
    assert trip_energy_kwh(150, True, VEHICLE) == pytest.approx(60 / 0.9)
    assert trip_energy_kwh(150, False, VEHICLE) == pytest.approx(30 / 0.9)
    assert trip_energy_kwh(0, True, VEHICLE) == 0


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


def test_pv_charge_time_within_horizon() -> None:
    # 9 kWh at 6 kW = 1.5 h of charging, even though the PV is spread over a gap
    s = [
        Slot(NOW, NOW + timedelta(hours=1), 6500),
        Slot(NOW + timedelta(hours=10), NOW + timedelta(hours=11), 6500),
    ]
    result = pv_charge_time(NOW, 9, s, 500, CHARGER)
    assert result == PvChargeTime(timedelta(hours=1.5), False)


def test_pv_charge_time_extrapolated() -> None:
    # 2 h at 6 kW = 12 kWh in the forecast; 30 kWh needs 5 h at the same rate
    result = pv_charge_time(NOW, 30, slots(6500, 6500), 500, CHARGER)
    assert result is not None
    assert result.extrapolated
    assert result.duration == timedelta(hours=5)


def test_pv_charge_time_no_surplus() -> None:
    assert pv_charge_time(NOW, 5, slots(3000, 3000), 500, CHARGER) is None
    assert pv_charge_time(NOW, 5, [], 500, CHARGER) is None


def test_pv_charge_time_nothing_needed() -> None:
    assert pv_charge_time(NOW, 0, [], 500, CHARGER) == PvChargeTime(timedelta(0), False)


SWITCHING = ChargerParams(p_min_w=4140, p_max_w=11000, phase_switching=True)


@pytest.mark.parametrize(
    ("surplus", "expected"),
    [
        (1000, 0),  # below 1φ minimum
        (1380, 1380),  # 1φ minimum
        (2500, 2500),  # 1φ
        (3680, 3680),  # 1φ maximum
        (3900, 3680),  # gap between 1φ max and 3φ min: stays at 1φ max
        (4140, 4140),  # 3φ minimum
        (15000, 11000),  # 3φ capped
    ],
)
def test_surplus_charge_power_phase_switching(surplus: float, expected: float) -> None:
    assert surplus_charge_power(surplus, SWITCHING) == expected


def test_pv_eta_small_system_needs_phase_switching() -> None:
    """5.35 kWp in autumn: ~4 kW peak minus ~530 W house load never reaches 3φ min."""
    s = slots(2500, 3500, 4000, 4000, 3500, 2500)
    assert pv_eta(NOW, 10, s, 530, CHARGER) is None
    eta = pv_eta(NOW, 10, s, 530, SWITCHING)
    assert eta is not None
    assert NOW + timedelta(hours=3) < eta < NOW + timedelta(hours=4)


def test_solar_share() -> None:
    half = ChargerParams(
        p_min_w=4140, p_max_w=11000, phase_switching=True, solar_share=0.5
    )
    assert surplus_charge_power(600, half) == 0  # below 50 % of 1380 W
    assert surplus_charge_power(700, half) == 1380  # grid tops up
    assert surplus_charge_power(0, ChargerParams(4140, 11000, solar_share=0)) == 0
    # 1 h at 700 W surplus -> 1.38 kWh, 0.68 kWh from grid
    result = pv_charge_time(NOW, 1.38, slots(1200), 500, half)
    assert result is not None
    assert result.duration == timedelta(hours=1)
    assert result.grid_kwh == pytest.approx(0.68)


def test_pv_phase() -> None:
    day = datetime(2026, 6, 1, tzinfo=UTC)
    end = day + timedelta(days=1)
    slots = [
        Slot(day + timedelta(hours=h), day + timedelta(hours=h + 1), w)
        for h, w in ((5, 0), (6, 800), (12, 3000), (19, 200), (20, 0))
    ]

    def phase(hour: float, pv_w: float | None) -> str:
        return pv_phase(day + timedelta(hours=hour), pv_w, slots, day, end)

    assert phase(4, 0) == PV_PHASE_BEFORE
    assert phase(4, None) == PV_PHASE_BEFORE
    assert phase(6.5, 900) == PV_PHASE_PRODUCING
    assert phase(12.5, 10) == PV_PHASE_PAUSED
    assert phase(12.5, None) == PV_PHASE_PRODUCING
    assert phase(20.5, 0) == PV_PHASE_AFTER
    assert phase(20.5, 120) == PV_PHASE_PRODUCING  # actual power wins
    # Tomorrow's forecast doesn't make tonight "before production".
    assert pv_phase(day + timedelta(hours=22), 0, slots, day, end) == PV_PHASE_AFTER
    assert pv_phase(
        end + timedelta(hours=1), 0, slots, end, end + timedelta(days=1)
    ) == (PV_PHASE_AFTER)
    assert pv_phase(day, 0, [], day, end) == PV_PHASE_AFTER


def test_with_live_pv_replaces_current_slot() -> None:
    start = NOW - timedelta(minutes=10)
    slots = [
        Slot(start, start + timedelta(hours=1), 1500),
        Slot(start + timedelta(hours=1), start + timedelta(hours=2), 2000),
    ]
    live = with_live_pv(NOW, 6000, slots)
    assert live == [
        Slot(start, NOW, 1500),
        Slot(NOW, NOW + LIVE_PV_HOLD, 6000),
        Slot(NOW + LIVE_PV_HOLD, start + timedelta(hours=1), 1500),
        slots[1],
    ]
    charger = ChargerParams(4100, 11000)
    # A low forecast no longer hides a surplus the panels produce right now.
    assert pv_energy_until(NOW, slots[-1].end, slots, 361, charger) == 0
    assert pv_energy_until(NOW, slots[-1].end, live, 361, charger) == pytest.approx(
        (6000 - 361) / 1000 * 0.5
    )


def test_with_live_pv_without_forecast_or_measurement() -> None:
    assert with_live_pv(NOW, 6000, []) == [Slot(NOW, NOW + LIVE_PV_HOLD, 6000)]
    assert with_live_pv(NOW, -20, []) == [Slot(NOW, NOW + LIVE_PV_HOLD, 0)]
    slots = [Slot(NOW + timedelta(minutes=10), NOW + timedelta(hours=1), 3000)]
    assert with_live_pv(NOW, None, slots) == slots
    # Live power only fills the gap up to the next forecast slot.
    assert with_live_pv(NOW, 6000, slots) == [
        Slot(NOW, NOW + timedelta(minutes=10), 6000),
        *slots,
    ]


def test_pv_projection_caps_at_target_and_matches_energy() -> None:
    # 8 kW for 4 h, 500 W baseline -> 7.5 kW surplus; 30 % SoC needs 25 kWh
    forecast = slots(8000, 8000, 8000, 8000)
    until = NOW + timedelta(hours=4)
    proj = pv_projection(NOW, until, 50, 80, forecast, 500, CHARGER, VEHICLE)
    assert proj.energy_kwh == pytest.approx(25.0)
    assert proj.soc == pytest.approx(80.0)
    assert proj.uncapped_kwh == pytest.approx(30.0)
    assert proj.uncapped_kwh == pytest.approx(
        pv_energy_until(NOW, until, forecast, 500, CHARGER)
    )
    assert proj.points[0].time == NOW
    assert proj.points[0].charge_w == 7500
    assert proj.points[-1].time == until
    # Once the target is reached the charger stops.
    assert proj.points[-2].charge_w == 0
    energies = [p.energy_kwh for p in proj.points]
    assert energies == sorted(energies)


def test_pv_projection_gaps_short_forecast_and_past_until() -> None:
    slots = [
        Slot(NOW, NOW + timedelta(hours=1), 8000),
        Slot(NOW + timedelta(hours=2), NOW + timedelta(hours=3), 8000),
    ]
    until = NOW + timedelta(hours=5)
    proj = pv_projection(NOW, until, 50, 100, slots, 500, CHARGER, VEHICLE)
    assert proj.energy_kwh == pytest.approx(15.0)
    times = [p.time - NOW for p in proj.points]
    assert times == [timedelta(hours=h) for h in (0, 1, 2, 3, 5)]
    assert [p.charge_w for p in proj.points] == [7500, 0, 7500, 0, 0]

    empty = pv_projection(
        NOW, NOW - timedelta(hours=1), 50, 80, slots, 500, CHARGER, VEHICLE
    )
    assert empty.energy_kwh == 0
    assert empty.points == []
    assert (
        pv_projection(NOW, until, 90, 80, slots, 500, CHARGER, VEHICLE).energy_kwh == 0
    )


def test_seasonal_km_per_kwh() -> None:
    assert seasonal_km_per_kwh(6, 4, None) == 6
    assert seasonal_km_per_kwh(6, 4, 25) == 6
    assert seasonal_km_per_kwh(6, 4, 20) == 6
    assert seasonal_km_per_kwh(6, 4, 10) == pytest.approx(5)
    assert seasonal_km_per_kwh(6, 4, 0) == 4
    assert seasonal_km_per_kwh(6, 4, -15) == 4
