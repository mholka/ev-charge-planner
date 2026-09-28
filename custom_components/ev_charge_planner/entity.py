"""Base entity for EV Charge Planner."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SCENARIO_FULL
from .coordinator import EvChargePlannerCoordinator, ScenarioResult


class EvChargePlannerEntity(CoordinatorEntity[EvChargePlannerCoordinator]):
    """Entity on the main "EV" device or on a trip's device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EvChargePlannerCoordinator,
        key: str,
        scenario_id: str = SCENARIO_FULL,
    ) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self.scenario_id = scenario_id
        self._attr_translation_key = key
        if scenario_id == SCENARIO_FULL:
            self._attr_unique_id = f"{entry.entry_id}_{key}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, entry.entry_id)},
                name="EV",
                entry_type=DeviceEntryType.SERVICE,
            )
        else:
            self._attr_unique_id = f"{scenario_id}_{key}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, scenario_id)},
                name=f"EV {coordinator.trips[scenario_id]['title']}",
                entry_type=DeviceEntryType.SERVICE,
                via_device=(DOMAIN, entry.entry_id),
            )

    @property
    def scenario(self) -> ScenarioResult | None:
        """Planner result for this entity's scenario."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.scenarios.get(self.scenario_id)
