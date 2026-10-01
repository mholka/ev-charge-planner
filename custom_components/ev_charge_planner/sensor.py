"""Sensors for EV Charge Planner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import MAIN_SCENARIOS, SCENARIO_QUICK_TRIP
from .coordinator import (
    EvChargePlannerConfigEntry,
    EvChargePlannerCoordinator,
    PlannerData,
    ScenarioResult,
)
from .entity import EvChargePlannerEntity, scenario_key
from .planner import PV_PHASES, PvProjection


@dataclass(frozen=True, kw_only=True)
class ScenarioSensorDescription(SensorEntityDescription):
    """Per-scenario sensor."""

    value_fn: Callable[[ScenarioResult], float | datetime | None]
    attrs_fn: Callable[[ScenarioResult], dict[str, Any]] | None = None


@dataclass(frozen=True, kw_only=True)
class PlannerSensorDescription(SensorEntityDescription):
    """Sensor on the main device."""

    value_fn: Callable[[PlannerData], float | str | datetime | None]
    attrs_fn: Callable[[PlannerData], dict[str, Any]] | None = None


def _departure_projection(data: PlannerData) -> PvProjection | None:
    return data.projection if data.projection_to_departure else None


def _pv_share(data: PlannerData) -> float | None:
    projection = _departure_projection(data)
    scenario = data.scenarios.get(data.projection_scenario or "")
    if projection is None or scenario is None:
        return None
    if scenario.energy_needed_kwh <= 0:
        return 100.0
    return round(
        min(100.0, projection.energy_kwh / scenario.energy_needed_kwh * 100), 1
    )


def _projection_attrs(data: PlannerData) -> dict[str, Any]:
    projection = data.projection
    if projection is None:
        return {}
    scenario = data.scenarios.get(data.projection_scenario or "")
    return {
        "until": projection.until,
        "uncapped_kwh": round(projection.uncapped_kwh, 2),
        "target_soc": None if scenario is None else scenario.target_soc,
        "grid_topup_kwh": None
        if data.deadline is None
        else round(data.deadline.grid_topup_kwh, 2),
        "projection": [
            {
                "time": p.time.isoformat(),
                "pv_w": round(p.pv_w),
                "surplus_w": round(p.surplus_w),
                "charge_w": round(p.charge_w),
                "energy_kwh": round(p.energy_kwh, 2),
                "soc": round(p.soc, 1),
            }
            for p in projection.points
        ],
    }


def _minutes(value: timedelta | None) -> float | None:
    return None if value is None else round(value.total_seconds() / 60, 1)


SCENARIO_SENSORS = (
    ScenarioSensorDescription(
        key="energy_needed",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=lambda s: round(s.energy_needed_kwh, 2),
    ),
    ScenarioSensorDescription(
        key="charge_time_grid",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda s: _minutes(s.charge_time_grid),
    ),
    ScenarioSensorDescription(
        key="charge_time_pv",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda s: _minutes(s.charge_time_pv),
        attrs_fn=lambda s: {
            "done_at": s.eta_pv,
            "extrapolated": s.charge_time_pv_extrapolated,
            "grid_topup_kwh": None
            if s.pv_grid_kwh is None
            else round(s.pv_grid_kwh, 2),
        },
    ),
    ScenarioSensorDescription(
        key="eta_grid",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: s.eta_grid,
    ),
    ScenarioSensorDescription(
        key="eta_pv",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: s.eta_pv,
    ),
)

# Only for trip scenarios (quick trip and trip subentries), not "full".
TRIP_ENERGY_SENSOR = ScenarioSensorDescription(
    key="trip_energy",
    device_class=SensorDeviceClass.ENERGY,
    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    suggested_display_precision=1,
    value_fn=lambda s: (
        None if s.trip_energy_kwh is None else round(s.trip_energy_kwh, 2)
    ),
)

PLANNER_SENSORS = (
    PlannerSensorDescription(
        key="deadline_grid_topup",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=lambda d: round(d.deadline.grid_topup_kwh, 2) if d.deadline else None,
    ),
    PlannerSensorDescription(
        key="latest_grid_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.deadline.latest_grid_start if d.deadline else None,
    ),
    PlannerSensorDescription(
        key="deadline_pv_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=lambda d: (
            None if (p := _departure_projection(d)) is None else round(p.energy_kwh, 2)
        ),
        attrs_fn=_projection_attrs,
    ),
    PlannerSensorDescription(
        key="deadline_soc_at_departure",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda d: (
            None if (p := _departure_projection(d)) is None else round(p.soc, 1)
        ),
    ),
    PlannerSensorDescription(
        key="deadline_pv_share",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=_pv_share,
    ),
    PlannerSensorDescription(
        key="consumption",
        native_unit_of_measurement="km/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value_fn=lambda d: (
            None if d.consumption is None else round(d.consumption.km_per_kwh, 2)
        ),
        attrs_fn=lambda d: {
            "temperature_c": None
            if d.consumption is None or d.consumption.temperature_c is None
            else round(d.consumption.temperature_c, 1)
        },
    ),
    PlannerSensorDescription(
        key="pv_phase",
        device_class=SensorDeviceClass.ENUM,
        options=list(PV_PHASES),
        value_fn=lambda d: d.pv_phase,
    ),
    PlannerSensorDescription(
        key="pv_surplus_forecast",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda d: round(d.forecast.today_kwh, 2),
        attrs_fn=lambda d: {
            "tomorrow_kwh": round(d.forecast.tomorrow_kwh, 2),
            "horizon_kwh": round(d.forecast.horizon_kwh, 2),
            "forecast_slots": d.forecast.slots,
            "horizon_end": d.forecast.horizon_end,
            "peak_forecast_w": round(d.forecast.peak_w),
            "live_pv_w": d.forecast.live_pv_w,
            "no_forecast_data": d.forecast.slots == 0,
            "entities_without_data": d.forecast.entities_without_data,
        },
    ),
    PlannerSensorDescription(
        key="house_baseline",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda d: round(d.baseline_w),
        attrs_fn=lambda d: {
            "nowcast_factor": round(d.nowcast_factor, 2),
            "charging_power_w": d.charging_power_w,
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargePlannerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(
                ScenarioSensor(coordinator, desc, scenario_id)
                for scenario_id in MAIN_SCENARIOS
                for desc in SCENARIO_SENSORS
            ),
            ScenarioSensor(coordinator, TRIP_ENERGY_SENSOR, SCENARIO_QUICK_TRIP),
            *(PlannerSensor(coordinator, desc) for desc in PLANNER_SENSORS),
        ]
    )
    for subentry_id in coordinator.trips:
        async_add_entities(
            [
                ScenarioSensor(coordinator, desc, subentry_id)
                for desc in (*SCENARIO_SENSORS, TRIP_ENERGY_SENSOR)
            ],
            config_subentry_id=subentry_id,
        )


class ScenarioSensor(EvChargePlannerEntity, SensorEntity):
    """Energy needed / ETA for one scenario."""

    _platform_domain = "sensor"

    entity_description: ScenarioSensorDescription

    def __init__(
        self,
        coordinator: EvChargePlannerCoordinator,
        description: ScenarioSensorDescription,
        scenario_id: str,
    ) -> None:
        key = description.key
        super().__init__(
            coordinator,
            scenario_key(scenario_id, key),
            scenario_id,
        )
        self.entity_description = description

    @property
    def native_value(self) -> float | datetime | None:
        scenario = self.scenario
        return None if scenario is None else self.entity_description.value_fn(scenario)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        scenario = self.scenario
        if scenario is None:
            return None
        attrs = {"target_soc": scenario.target_soc, "reachable": scenario.reachable}
        if scenario.trip_energy_kwh is not None:
            attrs["minimum_soc"] = self.coordinator.vehicle.reserve_pct
        if self.entity_description.attrs_fn is not None:
            attrs |= self.entity_description.attrs_fn(scenario)
        return attrs


class PlannerSensor(EvChargePlannerEntity, SensorEntity):
    """Deadline and diagnostic sensors."""

    # Up to ~100 points; useful for cards, too big for the database.
    _unrecorded_attributes = frozenset({"projection"})

    _platform_domain = "sensor"

    entity_description: PlannerSensorDescription

    def __init__(
        self,
        coordinator: EvChargePlannerCoordinator,
        description: PlannerSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | str | datetime | None:
        data = self.coordinator.data
        return None if data is None else self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if data is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(data)
