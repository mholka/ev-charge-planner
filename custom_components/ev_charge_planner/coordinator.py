"""Data update coordinator for EV Charge Planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .baseline import RollingAverage
from .const import (
    BASELINE_FIXED,
    CONF_BASELINE_FIXED_W,
    CONF_BASELINE_MODE,
    CONF_BASELINE_WINDOW_MIN,
    CONF_BATTERY_CAPACITY_KWH,
    CONF_CHARGE_EFFICIENCY,
    CONF_CHARGE_LIMIT_ENTITY,
    CONF_CHARGER_MAX_POWER_1P_W,
    CONF_CHARGER_MAX_POWER_W,
    CONF_CHARGER_MIN_POWER_1P_W,
    CONF_CHARGER_MIN_POWER_W,
    CONF_CONSUMPTION_KM_PER_KWH,
    CONF_DISTANCE_KM,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_EXTRA_ENTITIES,
    CONF_FORECAST_TOMORROW_ENTITY,
    CONF_HOUSE_LOAD_ENTITY,
    CONF_PHASE_SWITCHING,
    CONF_PV_POWER_ENTITY,
    CONF_ROUND_TRIP,
    CONF_SOC_ENTITY,
    CONF_SOC_RESERVE_PCT,
    CONF_WALLBOX_POWER_ENTITY,
    DEFAULTS,
    DOMAIN,
    SCENARIO_FULL,
    SUBENTRY_TRIP,
    UPDATE_INTERVAL,
)
from .forecast import merge_slots, parse_solcast
from .planner import (
    ChargerParams,
    DeadlineResult,
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
    trip_target_soc,
)

_LOGGER = logging.getLogger(__name__)

type EvChargePlannerConfigEntry = ConfigEntry[EvChargePlannerCoordinator]


@dataclass
class ScenarioResult:
    """Planner output for one target."""

    name: str
    target_soc: float
    reachable: bool
    energy_needed_kwh: float
    eta_grid: datetime
    eta_pv: datetime | None
    charge_time_grid: timedelta
    charge_time_pv: timedelta | None
    charge_time_pv_extrapolated: bool
    ready: bool


@dataclass
class ForecastSummary:
    """What the planner saw of the PV forecast (diagnostics)."""

    surplus_kwh: float
    slots: int
    horizon_end: datetime | None
    peak_w: float
    entities_without_data: list[str]


@dataclass
class PlannerData:
    """Everything the entities render."""

    soc: float
    baseline_w: float
    nowcast_factor: float
    charging_power_w: float | None
    forecast: ForecastSummary
    scenarios: dict[str, ScenarioResult] = field(default_factory=dict)
    deadline: DeadlineResult | None = None


def entry_config(entry: ConfigEntry) -> dict[str, Any]:
    """Merged config: defaults < data < options."""
    return {**DEFAULTS, **entry.data, **entry.options}


class EvChargePlannerCoordinator(DataUpdateCoordinator[PlannerData]):
    """Reads source entities and runs the planner."""

    config_entry: EvChargePlannerConfigEntry

    def __init__(self, hass: HomeAssistant, entry: EvChargePlannerConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.conf = entry_config(entry)
        self.vehicle = VehicleParams(
            capacity_kwh=float(self.conf[CONF_BATTERY_CAPACITY_KWH]),
            km_per_kwh=float(self.conf[CONF_CONSUMPTION_KM_PER_KWH]),
            efficiency=float(self.conf[CONF_CHARGE_EFFICIENCY]),
            reserve_pct=float(self.conf[CONF_SOC_RESERVE_PCT]),
        )
        self.charger = ChargerParams(
            p_min_w=float(self.conf[CONF_CHARGER_MIN_POWER_W]),
            p_max_w=float(self.conf[CONF_CHARGER_MAX_POWER_W]),
            phase_switching=bool(self.conf[CONF_PHASE_SWITCHING]),
            p_min_1p_w=float(self.conf[CONF_CHARGER_MIN_POWER_1P_W]),
            p_max_1p_w=float(self.conf[CONF_CHARGER_MAX_POWER_1P_W]),
        )
        self.baseline = RollingAverage(
            timedelta(minutes=float(self.conf[CONF_BASELINE_WINDOW_MIN]))
        )
        # Set by the datetime/select entities (restored on startup).
        self.deadline: datetime | None = None
        self.deadline_scenario: str = SCENARIO_FULL

    @property
    def forecast_entities(self) -> list[str]:
        """Configured forecast entities in horizon order."""
        entities = [
            self.conf.get(CONF_FORECAST_ENTITY),
            self.conf.get(CONF_FORECAST_TOMORROW_ENTITY),
            *(self.conf.get(CONF_FORECAST_EXTRA_ENTITIES) or []),
        ]
        return [e for e in entities if e]

    @property
    def trips(self) -> dict[str, dict[str, Any]]:
        """Trip subentries keyed by subentry id."""
        return {
            subentry_id: {"title": subentry.title, **subentry.data}
            for subentry_id, subentry in self.config_entry.subentries.items()
            if subentry.subentry_type == SUBENTRY_TRIP
        }

    @callback
    def async_setup_listeners(self) -> None:
        """Refresh on source changes and track house load for the baseline."""
        house = self.conf.get(CONF_HOUSE_LOAD_ENTITY)
        if house:
            self._record_house_load(self.hass.states.get(house))
            self.config_entry.async_on_unload(
                async_track_state_change_event(
                    self.hass, [house], self._handle_house_load_event
                )
            )

        triggers = [
            self.conf.get(CONF_SOC_ENTITY),
            self.conf.get(CONF_CHARGE_LIMIT_ENTITY),
            *self.forecast_entities,
        ]
        self.config_entry.async_on_unload(
            async_track_state_change_event(
                self.hass, [e for e in triggers if e], self._handle_trigger_event
            )
        )

    @callback
    def _handle_house_load_event(self, event: Event[EventStateChangedData]) -> None:
        self._record_house_load(event.data["new_state"])

    def _record_house_load(self, state: Any) -> None:
        if state is None:
            return
        try:
            value = float(state.state)
        except ValueError:
            return
        self.baseline.add(state.last_changed, value)

    @callback
    def _handle_trigger_event(self, event: Event[EventStateChangedData]) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    def _float_state(self, key: str) -> float | None:
        entity_id = self.conf.get(key)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def _baseline_w(self, now: datetime) -> float:
        if self.conf[CONF_BASELINE_MODE] == BASELINE_FIXED:
            return float(self.conf[CONF_BASELINE_FIXED_W])
        mean = self.baseline.mean(now)
        if mean is None:
            return float(self.conf[CONF_BASELINE_FIXED_W])
        return mean

    def _forecast_slots(self) -> tuple[list[Slot], list[str]]:
        """Merged slots and the forecast entities that provided none."""
        slot_lists = []
        missing = []
        for entity_id in self.forecast_entities:
            state = self.hass.states.get(entity_id)
            slots = parse_solcast(state.attributes) if state else []
            if not slots:
                missing.append(entity_id)
            slot_lists.append(slots)
        return merge_slots(*slot_lists), missing

    async def _async_update_data(self) -> PlannerData:
        now = dt_util.utcnow()
        soc = self._float_state(CONF_SOC_ENTITY)
        if soc is None:
            raise UpdateFailed(
                f"State of charge unavailable ({self.conf[CONF_SOC_ENTITY]})"
            )

        limit = self._float_state(CONF_CHARGE_LIMIT_ENTITY)
        slots, missing = self._forecast_slots()
        baseline_w = self._baseline_w(now)
        factor = nowcast_factor(
            self._float_state(CONF_PV_POWER_ENTITY), forecast_power_at(slots, now)
        )

        data = PlannerData(
            soc=soc,
            baseline_w=baseline_w,
            nowcast_factor=factor,
            charging_power_w=self._float_state(CONF_WALLBOX_POWER_ENTITY),
            forecast=ForecastSummary(
                surplus_kwh=pv_energy_until(
                    now,
                    slots[-1].end if slots else now,
                    slots,
                    baseline_w,
                    self.charger,
                    factor,
                ),
                slots=len(slots),
                horizon_end=slots[-1].end if slots else None,
                peak_w=max((s.pv_w for s in slots if s.end > now), default=0.0),
                entities_without_data=missing,
            ),
        )

        targets: dict[str, tuple[str, float]] = {
            SCENARIO_FULL: (SCENARIO_FULL, limit if limit is not None else 100.0)
        }
        for subentry_id, trip in self.trips.items():
            targets[subentry_id] = (
                trip["title"],
                trip_target_soc(
                    float(trip[CONF_DISTANCE_KM]),
                    bool(trip.get(CONF_ROUND_TRIP, False)),
                    self.vehicle,
                ),
            )

        for scenario_id, (name, raw_target) in targets.items():
            target = min(raw_target, 100.0)
            energy = energy_needed_kwh(soc, target, self.vehicle)
            eta_grid = grid_eta(now, energy, self.charger)
            eta_pv = pv_eta(now, energy, slots, baseline_w, self.charger, factor)
            pv_time = pv_charge_time(
                now, energy, slots, baseline_w, self.charger, factor
            )
            data.scenarios[scenario_id] = ScenarioResult(
                name=name,
                target_soc=round(raw_target, 1),
                reachable=raw_target <= 100.0,
                energy_needed_kwh=energy,
                eta_grid=eta_grid,
                eta_pv=eta_pv,
                charge_time_grid=eta_grid - now,
                charge_time_pv=None if pv_time is None else pv_time.duration,
                charge_time_pv_extrapolated=pv_time is not None
                and pv_time.extrapolated,
                ready=soc >= target,
            )

        scenario = data.scenarios.get(self.deadline_scenario)
        if self.deadline is not None and scenario is not None:
            data.deadline = deadline_plan(
                now,
                self.deadline,
                scenario.energy_needed_kwh,
                slots,
                baseline_w,
                self.charger,
                factor,
            )
        return data
