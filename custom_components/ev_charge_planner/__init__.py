"""EV Charge Planner integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import EvChargePlannerConfigEntry, EvChargePlannerCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.DATETIME,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: EvChargePlannerConfigEntry
) -> bool:
    """Set up EV Charge Planner from a config entry."""
    # "Won't be ready by departure" became "Will be ready on time" (inverted).
    registry = er.async_get(hass)
    if old := registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_deadline_at_risk"
    ):
        registry.async_remove(old)

    coordinator = EvChargePlannerCoordinator(hass, entry)
    coordinator.async_setup_listeners()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Options and trip subentry changes rebuild the coordinator and entities.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: EvChargePlannerConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(
    hass: HomeAssistant, entry: EvChargePlannerConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
