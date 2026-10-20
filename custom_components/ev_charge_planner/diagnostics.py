"""Diagnostics for EV Charge Planner (Settings → Devices & services → ⋮)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant

from .const import CONF_DISTANCE_KM, CONF_ROUND_TRIP, MAIN_SCENARIOS
from .coordinator import EvChargePlannerConfigEntry

# Source entities come from other integrations and can carry personal data
# (VIN, location, names), so only these attributes are copied.
_SOURCE_ATTRIBUTES = (
    "unit_of_measurement",
    "device_class",
    "state_class",
    "temperature",
    "temperature_unit",
)
# Big attributes (forecast lists) are summarised instead of copied.
_LIST_ATTRIBUTES = ("detailedForecast", "detailedHourly")


def _jsonable(value: Any) -> Any:
    """Durations as seconds; Home Assistant's encoder handles the rest."""
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EvChargePlannerConfigEntry
) -> dict[str, Any]:
    """Config, source entity states and the latest planner result."""
    coordinator = entry.runtime_data
    sources: dict[str, Any] = {}
    for key, value in coordinator.conf.items():
        for entity_id in value if isinstance(value, list) else [value]:
            if not isinstance(entity_id, str) or "." not in entity_id:
                continue
            state = hass.states.get(entity_id)
            if state is None:
                sources[entity_id] = {"setting": key, "state": None}
                continue
            attributes = {
                name: state.attributes[name]
                for name in _SOURCE_ATTRIBUTES
                if name in state.attributes
            }
            attributes.update(
                {
                    name: f"{len(state.attributes[name])} items"
                    for name in _LIST_ATTRIBUTES
                    if name in state.attributes
                }
            )
            sources[entity_id] = {
                "setting": key,
                "state": state.state,
                "attributes": attributes,
                "last_updated": state.last_updated,
            }

    # Trip names are free text; they are replaced by "Trip N" here.
    trip_labels = {
        trip_id: f"Trip {number}"
        for number, trip_id in enumerate(coordinator.trips, start=1)
    }
    trips = {
        trip_id: {
            "label": trip_labels[trip_id],
            CONF_DISTANCE_KM: trip[CONF_DISTANCE_KM],
            CONF_ROUND_TRIP: trip.get(CONF_ROUND_TRIP),
        }
        for trip_id, trip in coordinator.trips.items()
    }

    data = coordinator.data
    planner = None if data is None else _jsonable(asdict(data))
    if planner is not None:
        for scenario_id, scenario in planner["scenarios"].items():
            if scenario_id not in MAIN_SCENARIOS:
                scenario["name"] = trip_labels.get(scenario_id, "Trip")

    return {
        "config": coordinator.conf,
        "trips": trips,
        "runtime": {
            "deadline": coordinator.deadline,
            "deadline_scenario": coordinator.deadline_scenario,
            "quick_trip_km": coordinator.quick_trip_km,
            "quick_trip_round_trip": coordinator.quick_trip_round_trip,
            "last_update_success": coordinator.last_update_success,
            "last_exception": repr(coordinator.last_exception)
            if coordinator.last_exception
            else None,
        },
        "sources": sources,
        "planner": planner,
    }
