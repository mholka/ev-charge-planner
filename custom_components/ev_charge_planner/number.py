"""Number entities for EV Charge Planner."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_SOC_RESERVE_PCT
from .coordinator import EvChargePlannerConfigEntry, EvChargePlannerCoordinator
from .entity import EvChargePlannerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargePlannerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the quick trip distance and minimum battery level."""
    coordinator = entry.runtime_data
    async_add_entities([QuickTripDistance(coordinator), MinimumSoc(coordinator)])


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


class MinimumSoc(EvChargePlannerEntity, NumberEntity):
    """Minimum battery level for trips; the same value as in the options.

    Changing it stores the option, which reloads the entry like the options
    screen does.
    """

    _platform_domain = "number"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: EvChargePlannerCoordinator) -> None:
        super().__init__(coordinator, "minimum_soc")

    @property
    def native_value(self) -> float:
        return float(self.coordinator.conf[CONF_SOC_RESERVE_PCT])

    async def async_set_native_value(self, value: float) -> None:
        entry = self.coordinator.config_entry
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_SOC_RESERVE_PCT: value}
        )
