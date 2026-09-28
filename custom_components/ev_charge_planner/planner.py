"""Pure charge-planning logic. No Home Assistant imports, so it is unit-testable.

Energy figures are AC energy delivered by the wallbox (battery energy / efficiency).
Power figures are in W, energy in kWh, times are timezone-aware datetimes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

NOWCAST_MIN = 0.3
NOWCAST_MAX = 2.0
NOWCAST_MIN_FORECAST_W = 100.0
DEADLINE_RESOLUTION = timedelta(minutes=1)


@dataclass(frozen=True)
class VehicleParams:
    """Vehicle and consumption parameters."""

    capacity_kwh: float
    km_per_kwh: float
    efficiency: float
    reserve_pct: float = 0.0


@dataclass(frozen=True)
class ChargerParams:
    """Wallbox limits.

    p_min_w / p_max_w are the three-phase (or only) range. With phase switching
    the wallbox also runs on one phase between p_min_1p_w and p_max_1p_w.
    """

    p_min_w: float
    p_max_w: float
    phase_switching: bool = False
    p_min_1p_w: float = 1380.0
    p_max_1p_w: float = 3680.0
    # Share of the minimum charging power that must come from PV (evcc "solar
    # share"). Below 1.0 the grid tops up weak surplus to the minimum power.
    solar_share: float = 1.0

    @property
    def lowest_power_w(self) -> float:
        """Lowest power the wallbox can charge at."""
        return self.p_min_1p_w if self.phase_switching else self.p_min_w


@dataclass(frozen=True)
class Slot:
    """Forecast slot with average PV power over [start, end)."""

    start: datetime
    end: datetime
    pv_w: float


@dataclass(frozen=True)
class PvRun:
    """Result of simulating PV surplus charging."""

    energy_kwh: float
    eta: datetime | None
    charging_hours: float
    grid_kwh: float = 0.0


@dataclass(frozen=True)
class PvChargeTime:
    """How long the charger has to run on PV surplus to deliver the energy."""

    duration: timedelta
    extrapolated: bool
    grid_kwh: float = 0.0


@dataclass(frozen=True)
class DeadlineResult:
    """Answer to "need the energy by the deadline"."""

    grid_topup_kwh: float
    latest_grid_start: datetime | None
    at_risk: bool


def trip_target_soc(
    distance_km: float, round_trip: bool, vehicle: VehicleParams
) -> float:
    """SoC (%) needed to drive a trip and arrive with the reserve. May exceed 100."""
    km = distance_km * (2 if round_trip else 1)
    return vehicle.reserve_pct + km / vehicle.km_per_kwh / vehicle.capacity_kwh * 100


def energy_needed_kwh(soc: float, target_soc: float, vehicle: VehicleParams) -> float:
    """AC energy (kWh) needed to go from soc to target_soc."""
    return max(0.0, target_soc - soc) / 100 * vehicle.capacity_kwh / vehicle.efficiency


def grid_eta(now: datetime, energy_kwh: float, charger: ChargerParams) -> datetime:
    """ETA when charging at full wallbox power."""
    if energy_kwh <= 0:
        return now
    return now + timedelta(hours=energy_kwh * 1000 / charger.p_max_w)


def surplus_charge_power(surplus_w: float, charger: ChargerParams) -> float:
    """Charging power the wallbox can run at for a given PV surplus."""
    if surplus_w >= charger.p_min_w:
        return min(surplus_w, charger.p_max_w)
    if charger.phase_switching and surplus_w >= charger.p_min_1p_w:
        # One phase; between 1φ max and 3φ min it stays on 1φ at max power.
        return min(surplus_w, charger.p_max_1p_w)
    if (
        charger.solar_share < 1.0
        and surplus_w > 0
        and surplus_w >= charger.solar_share * charger.lowest_power_w
    ):
        # Grid tops up the missing part of the minimum power.
        return charger.lowest_power_w
    return 0.0


def forecast_power_at(slots: Sequence[Slot], when: datetime) -> float | None:
    """Forecast PV power of the slot containing `when`, None if not covered."""
    for slot in slots:
        if slot.start <= when < slot.end:
            return slot.pv_w
    return None


def nowcast_factor(actual_pv_w: float | None, forecast_pv_w: float | None) -> float:
    """Correction factor for the current slot from actual vs. forecast PV power."""
    if (
        actual_pv_w is None
        or forecast_pv_w is None
        or forecast_pv_w < NOWCAST_MIN_FORECAST_W
    ):
        return 1.0
    return min(NOWCAST_MAX, max(NOWCAST_MIN, actual_pv_w / forecast_pv_w))


def _simulate_pv(
    now: datetime,
    slots: Sequence[Slot],
    baseline_w: float,
    charger: ChargerParams,
    factor: float,
    until: datetime | None = None,
    target_kwh: float | None = None,
) -> PvRun:
    """Charge from PV surplus from now on.

    Stops at `until` or when `target_kwh` is reached. Returns the energy charged,
    the time the target was reached (None if not reached) and the hours the
    charger actually ran. Gaps between slots and time past the last slot count
    as zero PV.
    """
    energy = 0.0
    grid = 0.0
    charging_hours = 0.0
    for slot in sorted(slots, key=lambda s: s.start):
        start = max(slot.start, now)
        end = slot.end if until is None else min(slot.end, until)
        if end <= start:
            if until is not None and slot.start >= until:
                break
            continue
        pv = slot.pv_w * (factor if slot.start <= now < slot.end else 1.0)
        surplus_w = pv - baseline_w
        power_kw = surplus_charge_power(surplus_w, charger) / 1000
        if power_kw <= 0:
            continue
        grid_kw = max(0.0, power_kw - max(0.0, surplus_w) / 1000)
        hours = (end - start).total_seconds() / 3600
        if target_kwh is not None and energy + power_kw * hours >= target_kwh:
            needed_hours = (target_kwh - energy) / power_kw
            return PvRun(
                target_kwh,
                start + timedelta(hours=needed_hours),
                charging_hours + needed_hours,
                grid + grid_kw * needed_hours,
            )
        energy += power_kw * hours
        grid += grid_kw * hours
        charging_hours += hours
    return PvRun(energy, None, charging_hours, grid)


def pv_eta(
    now: datetime,
    energy_kwh: float,
    slots: Sequence[Slot],
    baseline_w: float,
    charger: ChargerParams,
    factor: float = 1.0,
) -> datetime | None:
    """ETA charging from PV surplus only; None if not reached within the forecast."""
    if energy_kwh <= 0:
        return now
    return _simulate_pv(
        now, slots, baseline_w, charger, factor, target_kwh=energy_kwh
    ).eta


def pv_charge_time(
    now: datetime,
    energy_kwh: float,
    slots: Sequence[Slot],
    baseline_w: float,
    charger: ChargerParams,
    factor: float = 1.0,
) -> PvChargeTime | None:
    """Time the charger runs on PV surplus to deliver `energy_kwh` (nights excluded).

    If the forecast horizon is too short, the rest is extrapolated at the average
    PV charging power seen in the forecast. None if the forecast has no usable
    surplus at all.
    """
    if energy_kwh <= 0:
        return PvChargeTime(timedelta(0), False)
    run = _simulate_pv(now, slots, baseline_w, charger, factor, target_kwh=energy_kwh)
    if run.eta is not None:
        return PvChargeTime(timedelta(hours=run.charging_hours), False, run.grid_kwh)
    if run.charging_hours <= 0:
        return None
    avg_kw = run.energy_kwh / run.charging_hours
    hours = run.charging_hours + (energy_kwh - run.energy_kwh) / avg_kw
    # Assume the same grid top-up ratio for the extrapolated part.
    grid = run.grid_kwh * energy_kwh / run.energy_kwh
    return PvChargeTime(timedelta(hours=hours), True, grid)


def pv_energy_until(
    now: datetime,
    until: datetime,
    slots: Sequence[Slot],
    baseline_w: float,
    charger: ChargerParams,
    factor: float = 1.0,
) -> float:
    """Energy (kWh) PV surplus charging delivers between now and `until`."""
    if until <= now:
        return 0.0
    return _simulate_pv(now, slots, baseline_w, charger, factor, until=until).energy_kwh


def deadline_plan(
    now: datetime,
    deadline: datetime,
    energy_kwh: float,
    slots: Sequence[Slot],
    baseline_w: float,
    charger: ChargerParams,
    factor: float = 1.0,
) -> DeadlineResult:
    """Hybrid plan: PV surplus first, then full power from `latest_grid_start`.

    Once grid charging starts the wallbox runs at P_max regardless of source, so
    only PV before the grid start counts: find the latest s with
    pv(now, s) + P_max * (deadline - s) >= energy. The left side is
    non-increasing in s, so bisection works.
    """
    if energy_kwh <= 0:
        return DeadlineResult(0.0, None, False)
    if deadline <= now:
        return DeadlineResult(energy_kwh, None, True)

    p_max_kw = charger.p_max_w / 1000

    def pv(s: datetime) -> float:
        return pv_energy_until(now, s, slots, baseline_w, charger, factor)

    def deliverable(s: datetime) -> float:
        return pv(s) + p_max_kw * (deadline - s).total_seconds() / 3600

    if pv(deadline) >= energy_kwh:
        return DeadlineResult(0.0, None, False)
    if deliverable(now) < energy_kwh:
        return DeadlineResult(energy_kwh - pv(now), now, True)

    lo, hi = now, deadline  # deliverable(lo) >= energy > deliverable(hi)
    while hi - lo > DEADLINE_RESOLUTION:
        mid = lo + (hi - lo) / 2
        if deliverable(mid) >= energy_kwh:
            lo = mid
        else:
            hi = mid
    return DeadlineResult(energy_kwh - pv(lo), lo, lo <= now)
