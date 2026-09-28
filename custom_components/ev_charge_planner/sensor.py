"""Sensors for EV Charge Planner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SCENARIO_FULL
from .coordinator import (
    EvChargePlannerConfigEntry,
    EvChargePlannerCoordinator,
    PlannerData,
    ScenarioResult,
)
from .entity import EvChargePlannerEntity


@dataclass(frozen=True, kw_only=True)
class ScenarioSensorDescription(SensorEntityDescription):
    """Per-scenario sensor."""

    value_fn: Callable[[ScenarioResult], float | datetime | None]


@dataclass(frozen=True, kw_only=True)
class PlannerSensorDescription(SensorEntityDescription):
    """Sensor on the main device."""

    value_fn: Callable[[PlannerData], float | datetime | None]
    attrs_fn: Callable[[PlannerData], dict[str, Any]] | None = None


SCENARIO_SENSORS = (
    ScenarioSensorDescription(
        key="energy_needed",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=lambda s: round(s.energy_needed_kwh, 2),
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
                ScenarioSensor(coordinator, desc, SCENARIO_FULL)
                for desc in SCENARIO_SENSORS
            ),
            *(PlannerSensor(coordinator, desc) for desc in PLANNER_SENSORS),
        ]
    )
    for subentry_id in coordinator.trips:
        async_add_entities(
            [
                ScenarioSensor(coordinator, desc, subentry_id)
                for desc in SCENARIO_SENSORS
            ],
            config_subentry_id=subentry_id,
        )


class ScenarioSensor(EvChargePlannerEntity, SensorEntity):
    """Energy needed / ETA for one scenario."""

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
            f"full_{key}" if scenario_id == SCENARIO_FULL else key,
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
        return {"target_soc": scenario.target_soc, "reachable": scenario.reachable}


class PlannerSensor(EvChargePlannerEntity, SensorEntity):
    """Deadline and diagnostic sensors."""

    entity_description: PlannerSensorDescription

    def __init__(
        self,
        coordinator: EvChargePlannerCoordinator,
        description: PlannerSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | datetime | None:
        data = self.coordinator.data
        return None if data is None else self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if data is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(data)
