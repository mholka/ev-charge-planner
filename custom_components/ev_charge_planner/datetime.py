"""Deadline datetime entity for EV Charge Planner."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .coordinator import EvChargePlannerConfigEntry, EvChargePlannerCoordinator
from .entity import EvChargePlannerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargePlannerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the deadline entity."""
    async_add_entities([DeadlineEntity(entry.runtime_data)])


class DeadlineEntity(EvChargePlannerEntity, DateTimeEntity, RestoreEntity):
    """When the deadline scenario's target must be reached."""

    def __init__(self, coordinator: EvChargePlannerCoordinator) -> None:
        super().__init__(coordinator, "deadline")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (
            self.coordinator.deadline is None
            and (last := await self.async_get_last_state()) is not None
            and (restored := dt_util.parse_datetime(last.state)) is not None
        ):
            self.coordinator.deadline = restored
            await self.coordinator.async_refresh()

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.deadline

    async def async_set_value(self, value: datetime) -> None:
        self.coordinator.deadline = value
        self.async_write_ha_state()
        await self.coordinator.async_refresh()
