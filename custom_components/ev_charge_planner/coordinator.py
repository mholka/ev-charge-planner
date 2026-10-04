"""Data update coordinator for EV Charge Planner."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature
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
    CONF_BATTERY_HEALTH_PCT,
    CONF_CHARGE_EFFICIENCY,
    CONF_CHARGE_LIMIT_ENTITY,
    CONF_CHARGER_MAX_POWER_1P_W,
    CONF_CHARGER_MAX_POWER_W,
    CONF_CHARGER_MIN_POWER_1P_W,
    CONF_CHARGER_MIN_POWER_W,
    CONF_CONSUMPTION_COLD_KM_PER_KWH,
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
    CONF_SOLAR_SHARE_PCT,
    CONF_TEMPERATURE_ENTITY,
    CONF_WALLBOX_POWER_ENTITY,
    DEFAULTS,
    DOMAIN,
    MAIN_SCENARIOS,
    SCENARIO_FULL,
    SCENARIO_QUICK_TRIP,
    SUBENTRY_TRIP,
    UPDATE_INTERVAL,
)
from .forecast import merge_slots, parse_solcast
from .planner import (
    ChargerParams,
    DeadlineResult,
    PvProjection,
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
    trip_energy_kwh,
    trip_target_soc,
    with_live_pv,
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
    pv_grid_kwh: float | None
    ready: bool
    # Energy the trip itself uses; None for the "full" scenario.
    trip_energy_kwh: float | None = None


@dataclass
class ForecastSummary:
    """What the planner saw of the PV forecast (diagnostics)."""

    today_kwh: float
    tomorrow_kwh: float
    horizon_kwh: float
    slots: int
    horizon_end: datetime | None
    peak_w: float
    live_pv_w: float | None
    entities_without_data: list[str]


@dataclass
class ConsumptionSummary:
    """Consumption the planner used and why."""

    km_per_kwh: float
    temperature_c: float | None


@dataclass
class PlannerData:
    """Everything the entities render."""

    soc: float
    baseline_w: float
    nowcast_factor: float
    charging_power_w: float | None
    forecast: ForecastSummary
    pv_phase: str
    consumption: ConsumptionSummary | None = None
    scenarios: dict[str, ScenarioResult] = field(default_factory=dict)
    deadline: DeadlineResult | None = None
    # PV charging for the "Charge for" scenario until departure, or over the
    # whole forecast without a (future) departure time.
    projection: PvProjection | None = None
    projection_to_departure: bool = False
    projection_scenario: str | None = None


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
            health_pct=float(self.conf[CONF_BATTERY_HEALTH_PCT]),
        )
        self.charger = ChargerParams(
            p_min_w=float(self.conf[CONF_CHARGER_MIN_POWER_W]),
            p_max_w=float(self.conf[CONF_CHARGER_MAX_POWER_W]),
            phase_switching=bool(self.conf[CONF_PHASE_SWITCHING]),
            p_min_1p_w=float(self.conf[CONF_CHARGER_MIN_POWER_1P_W]),
            p_max_1p_w=float(self.conf[CONF_CHARGER_MAX_POWER_1P_W]),
            solar_share=float(self.conf[CONF_SOLAR_SHARE_PCT]) / 100,
        )
        self.baseline = RollingAverage(
            timedelta(minutes=float(self.conf[CONF_BASELINE_WINDOW_MIN]))
        )
        # Set by the datetime/select entities (restored on startup).
        self.deadline: datetime | None = None
        self.deadline_scenario: str = SCENARIO_FULL
        # Set by the quick trip number/switch entities (restored on startup).
        self.quick_trip_km: float = 0.0
        self.quick_trip_round_trip: bool = True

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
            _LOGGER.debug(
                "%s (%s) has no value: %s",
                key,
                entity_id,
                "missing" if state is None else state.state,
            )
            return None
        try:
            return float(state.state)
        except ValueError:
            _LOGGER.debug("%s (%s) isn't numeric: %r", key, entity_id, state.state)
            return None

    def _temperature_c(self) -> float | None:
        """Outdoor temperature in °C from a sensor or weather entity."""
        entity_id = self.conf.get(CONF_TEMPERATURE_ENTITY)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None:
            return None
        if state.domain == "weather":
            raw = state.attributes.get("temperature")
            unit = state.attributes.get("temperature_unit")
        else:
            raw = state.state
            unit = state.attributes.get("unit_of_measurement")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            _LOGGER.debug("Temperature (%s) isn't numeric: %r", entity_id, raw)
            return None
        if unit == UnitOfTemperature.FAHRENHEIT:
            return (value - 32) * 5 / 9
        return value

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
            _LOGGER.debug("Forecast %s: %d slots", entity_id, len(slots))
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
        temperature = self._temperature_c()
        km_per_kwh = seasonal_km_per_kwh(
            float(self.conf[CONF_CONSUMPTION_KM_PER_KWH]),
            float(self.conf[CONF_CONSUMPTION_COLD_KM_PER_KWH]),
            temperature,
        )
        self.vehicle = replace(self.vehicle, km_per_kwh=km_per_kwh)
        slots, missing = self._forecast_slots()
        baseline_w = self._baseline_w(now)
        pv_w = self._float_state(CONF_PV_POWER_ENTITY)
        factor = nowcast_factor(pv_w, forecast_power_at(slots, now))
        forecast_slots = slots
        # The measured PV replaces the nowcast-scaled forecast for the near term.
        slots = with_live_pv(now, pv_w, slots)
        day_start = dt_util.start_of_local_day()
        day_end = day_start + timedelta(days=1)
        horizon_end = slots[-1].end if slots else now

        def surplus_kwh(start: datetime, end: datetime) -> float:
            return pv_energy_until(start, end, slots, baseline_w, self.charger)

        data = PlannerData(
            soc=soc,
            baseline_w=baseline_w,
            nowcast_factor=factor,
            charging_power_w=self._float_state(CONF_WALLBOX_POWER_ENTITY),
            forecast=ForecastSummary(
                today_kwh=surplus_kwh(now, day_end),
                tomorrow_kwh=surplus_kwh(day_end, day_end + timedelta(days=1)),
                horizon_kwh=surplus_kwh(now, horizon_end),
                slots=len(forecast_slots),
                horizon_end=slots[-1].end if slots else None,
                live_pv_w=pv_w,
                peak_w=max(
                    (s.pv_w for s in forecast_slots if s.end > now), default=0.0
                ),
                entities_without_data=missing,
            ),
            consumption=ConsumptionSummary(km_per_kwh, temperature),
            pv_phase=pv_phase(now, pv_w, forecast_slots, day_start, day_end),
        )

        trips: dict[str, tuple[str, float, bool]] = {
            SCENARIO_QUICK_TRIP: (
                SCENARIO_QUICK_TRIP,
                self.quick_trip_km,
                self.quick_trip_round_trip,
            ),
            **{
                subentry_id: (
                    trip["title"],
                    float(trip[CONF_DISTANCE_KM]),
                    bool(trip.get(CONF_ROUND_TRIP, False)),
                )
                for subentry_id, trip in self.trips.items()
            },
        }
        targets: dict[str, tuple[str, float, float | None]] = {
            SCENARIO_FULL: (
                SCENARIO_FULL,
                limit if limit is not None else 100.0,
                None,
            ),
            **{
                scenario_id: (
                    name,
                    trip_target_soc(km, round_trip, self.vehicle),
                    trip_energy_kwh(km, round_trip, self.vehicle),
                )
                for scenario_id, (name, km, round_trip) in trips.items()
            },
        }

        for scenario_id, (name, raw_target, trip_kwh) in targets.items():
            target = min(raw_target, 100.0)
            energy = energy_needed_kwh(soc, target, self.vehicle)
            eta_grid = grid_eta(now, energy, self.charger)
            eta_pv = pv_eta(now, energy, slots, baseline_w, self.charger)
            pv_time = pv_charge_time(now, energy, slots, baseline_w, self.charger)
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
                pv_grid_kwh=None if pv_time is None else pv_time.grid_kwh,
                ready=soc >= target,
                trip_energy_kwh=trip_kwh,
            )

        scenario = data.scenarios.get(self.deadline_scenario)
        if scenario is not None:
            to_departure = self.deadline is not None and self.deadline > now
            data.projection_to_departure = to_departure
            data.projection_scenario = self.deadline_scenario
            data.projection = pv_projection(
                now,
                self.deadline if to_departure else horizon_end,
                soc,
                min(scenario.target_soc, 100.0),
                slots,
                baseline_w,
                self.charger,
                self.vehicle,
            )
        if self.deadline is not None and scenario is not None:
            data.deadline = deadline_plan(
                now,
                self.deadline,
                scenario.energy_needed_kwh,
                slots,
                baseline_w,
                self.charger,
            )
        self._log_summary(data, pv_w, len(forecast_slots))
        return data

    def _log_summary(self, data: PlannerData, pv_w: float | None, slots: int) -> None:
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        consumption = data.consumption
        _LOGGER.debug(
            "Inputs: SoC %.1f %%, PV %s W, house baseline %.0f W, %s km/kWh "
            "(temperature %s °C), %d forecast slots",
            data.soc,
            pv_w,
            data.baseline_w,
            None if consumption is None else round(consumption.km_per_kwh, 2),
            None if consumption is None else consumption.temperature_c,
            slots,
        )
        _LOGGER.debug(
            "Solar for the car: today %.2f kWh, tomorrow %.2f kWh, horizon %.2f kWh",
            data.forecast.today_kwh,
            data.forecast.tomorrow_kwh,
            data.forecast.horizon_kwh,
        )
        for scenario_id, s in data.scenarios.items():
            _LOGGER.debug(
                "Scenario %s: target %.1f %%, %.2f kWh to charge, "
                "ready at %s (grid) / %s (solar)",
                s.name
                if scenario_id in MAIN_SCENARIOS
                else f"{s.name} ({scenario_id})",
                s.target_soc,
                s.energy_needed_kwh,
                s.eta_grid,
                s.eta_pv,
            )
        if data.deadline is not None:
            _LOGGER.debug(
                "Departure %s for %s: grid top-up %.2f kWh, latest grid start %s, "
                "at risk %s",
                self.deadline,
                self.deadline_scenario,
                data.deadline.grid_topup_kwh,
                data.deadline.latest_grid_start,
                data.deadline.at_risk,
            )
