"""Binary sensors for EV Charge Planner."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SCENARIO_FULL
from .coordinator import EvChargePlannerConfigEntry, EvChargePlannerCoordinator
from .entity import EvChargePlannerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargePlannerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [ReadySensor(coordinator, SCENARIO_FULL), DeadlineAtRiskSensor(coordinator)]
    )
    for subentry_id in coordinator.trips:
        async_add_entities(
            [ReadySensor(coordinator, subentry_id)], config_subentry_id=subentry_id
        )


class ReadySensor(EvChargePlannerEntity, BinarySensorEntity):
    """On when SoC has reached the scenario target."""

    def __init__(
        self, coordinator: EvChargePlannerCoordinator, scenario_id: str
    ) -> None:
        super().__init__(
            coordinator,
            "full_ready" if scenario_id == SCENARIO_FULL else "ready",
            scenario_id,
        )

    @property
    def is_on(self) -> bool | None:
        scenario = self.scenario
        return None if scenario is None else scenario.ready


class DeadlineAtRiskSensor(EvChargePlannerEntity, BinarySensorEntity):
    """On when the deadline target cannot be met even with grid charging from now."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: EvChargePlannerCoordinator) -> None:
        super().__init__(coordinator, "deadline_at_risk")

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None or data.deadline is None:
            return None
        return data.deadline.at_risk
