"""Test helpers."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.ev_charge_planner.const import (
    CONF_BATTERY_CAPACITY_KWH,
    CONF_CHARGE_LIMIT_ENTITY,
    CONF_FORECAST_ENTITY,
    CONF_HOUSE_LOAD_ENTITY,
    CONF_PV_POWER_ENTITY,
    CONF_SOC_ENTITY,
    DEFAULTS,
)

ENTITIES = {
    CONF_SOC_ENTITY: "sensor.tesla_battery",
    CONF_CHARGE_LIMIT_ENTITY: "number.tesla_charge_limit",
    CONF_PV_POWER_ENTITY: "sensor.pv_power",
    CONF_HOUSE_LOAD_ENTITY: "sensor.house_load",
    CONF_FORECAST_ENTITY: "sensor.solcast_today",
}
CONFIG = {**DEFAULTS, **ENTITIES, CONF_BATTERY_CAPACITY_KWH: 75.0}


def set_sources(
    hass: HomeAssistant, soc: float = 50, limit: float = 80, pv_kw: float = 0
) -> None:
    """Populate source entity states."""
    hass.states.async_set(ENTITIES[CONF_SOC_ENTITY], str(soc))
    hass.states.async_set(ENTITIES[CONF_CHARGE_LIMIT_ENTITY], str(limit))
    hass.states.async_set(ENTITIES[CONF_PV_POWER_ENTITY], str(pv_kw * 1000))
    hass.states.async_set(ENTITIES[CONF_HOUSE_LOAD_ENTITY], "500")
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    hass.states.async_set(
        ENTITIES[CONF_FORECAST_ENTITY],
        "10",
        {
            "detailedForecast": [
                {
                    "period_start": start + timedelta(minutes=30 * i),
                    "pv_estimate": pv_kw,
                }
                for i in range(48)
            ]
        },
    )
