"""Quick trip distance for EV Charge Planner."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import EvChargePlannerConfigEntry, EvChargePlannerCoordinator
from .entity import EvChargePlannerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargePlannerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the quick trip distance."""
    async_add_entities([QuickTripDistance(entry.runtime_data)])


class QuickTripDistance(EvChargePlannerEntity, RestoreNumber):
    """One-way distance of an ad-hoc trip."""

    _platform_domain = "number"
    _attr_native_min_value = 0
    _attr_native_max_value = 2000
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: EvChargePlannerCoordinator) -> None:
        super().__init__(coordinator, "quick_trip_distance")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self.coordinator.quick_trip_km = float(last.native_value)
            await self.coordinator.async_refresh()

    @property
    def native_value(self) -> float:
        return self.coordinator.quick_trip_km

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.quick_trip_km = value
        self.async_write_ha_state()
        await self.coordinator.async_refresh()
