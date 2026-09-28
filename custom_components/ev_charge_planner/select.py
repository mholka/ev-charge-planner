"""Deadline scenario select for EV Charge Planner."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import SCENARIO_FULL
from .coordinator import EvChargePlannerConfigEntry, EvChargePlannerCoordinator
from .entity import EvChargePlannerEntity

FULL_OPTION = "Full"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargePlannerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the deadline scenario select."""
    async_add_entities([DeadlineScenarioSelect(entry.runtime_data)])


class DeadlineScenarioSelect(EvChargePlannerEntity, SelectEntity, RestoreEntity):
    """Which scenario the deadline sensors plan for."""

    def __init__(self, coordinator: EvChargePlannerCoordinator) -> None:
        super().__init__(coordinator, "deadline_scenario")
        self._ids_by_option = {FULL_OPTION: SCENARIO_FULL} | {
            trip["title"]: subentry_id
            for subentry_id, trip in coordinator.trips.items()
        }
        self._attr_options = list(self._ids_by_option)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._ids_by_option:
            self.coordinator.deadline_scenario = self._ids_by_option[last.state]
            await self.coordinator.async_refresh()

    @property
    def current_option(self) -> str:
        for option, scenario_id in self._ids_by_option.items():
            if scenario_id == self.coordinator.deadline_scenario:
                return option
        return FULL_OPTION

    async def async_select_option(self, option: str) -> None:
        self.coordinator.deadline_scenario = self._ids_by_option[option]
        self.async_write_ha_state()
        await self.coordinator.async_refresh()
