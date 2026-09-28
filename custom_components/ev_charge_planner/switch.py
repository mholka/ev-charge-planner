"""Quick trip round-trip switch for EV Charge Planner."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import EvChargePlannerConfigEntry, EvChargePlannerCoordinator
from .entity import EvChargePlannerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargePlannerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the quick trip round-trip switch."""
    async_add_entities([QuickTripRoundTrip(entry.runtime_data)])


class QuickTripRoundTrip(EvChargePlannerEntity, SwitchEntity, RestoreEntity):
    """Whether the quick trip distance is driven there and back."""

    _platform_domain = "switch"

    def __init__(self, coordinator: EvChargePlannerCoordinator) -> None:
        super().__init__(coordinator, "quick_trip_round_trip")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in (STATE_ON, STATE_OFF):
            self.coordinator.quick_trip_round_trip = last.state == STATE_ON
            await self.coordinator.async_refresh()

    @property
    def is_on(self) -> bool:
        return self.coordinator.quick_trip_round_trip

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, value: bool) -> None:
        self.coordinator.quick_trip_round_trip = value
        self.async_write_ha_state()
        await self.coordinator.async_refresh()
