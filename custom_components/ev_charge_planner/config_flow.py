"""Config, options and trip subentry flows for EV Charge Planner."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    BASELINE_FIXED,
    BASELINE_ROLLING,
    CONF_BASELINE_FIXED_W,
    CONF_BASELINE_MODE,
    CONF_BASELINE_WINDOW_MIN,
    CONF_BATTERY_CAPACITY_KWH,
    CONF_BATTERY_HEALTH_PCT,
    CONF_CHARGE_EFFICIENCY,
    CONF_CHARGE_LIMIT_ENTITY,
    CONF_CHARGER_MAX_POWER_1P_W,
    CONF_CHARGER_MAX_POWER_W,
    CONF_CHARGER_MIN_POWER_1P_W,
    CONF_CHARGER_MIN_POWER_W,
    CONF_CONSUMPTION_COLD_KM_PER_KWH,
    CONF_CONSUMPTION_KM_PER_KWH,
    CONF_DISTANCE_KM,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_EXTRA_ENTITIES,
    CONF_FORECAST_TOMORROW_ENTITY,
    CONF_HOUSE_LOAD_ENTITY,
    CONF_PHASE_SWITCHING,
    CONF_PV_POWER_ENTITY,
    CONF_ROUND_TRIP,
    CONF_SOC_ENTITY,
    CONF_SOC_RESERVE_PCT,
    CONF_SOLAR_SHARE_PCT,
    CONF_TEMPERATURE_ENTITY,
    CONF_TRIP_NAME,
    CONF_WALLBOX_POWER_ENTITY,
    DEFAULTS,
    DOMAIN,
    SUBENTRY_TRIP,
)
from .coordinator import entry_config

_SENSOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
_SENSOR_OR_NUMBER = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["sensor", "number", "input_number"])
)

_TEMPERATURE = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["sensor", "weather"])
)
_SENSORS_MULTI = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", multiple=True)
)

_REQUIRED_ENTITIES = (
    CONF_SOC_ENTITY,
    CONF_PV_POWER_ENTITY,
    CONF_HOUSE_LOAD_ENTITY,
    CONF_FORECAST_ENTITY,
)
_OPTIONAL_ENTITIES = (
    CONF_CHARGE_LIMIT_ENTITY,
    CONF_WALLBOX_POWER_ENTITY,
    CONF_FORECAST_TOMORROW_ENTITY,
    CONF_FORECAST_EXTRA_ENTITIES,
    CONF_TEMPERATURE_ENTITY,
)


def _number(
    min_: float, max_: float, step: float | str, unit: str | None = None
) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(
        min=min_, max=max_, step=step, mode=selector.NumberSelectorMode.BOX
    )
    if unit is not None:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


_PARAM_SELECTORS: dict[str, selector.Selector] = {
    CONF_BATTERY_CAPACITY_KWH: _number(5, 250, 0.1, "kWh"),
    CONF_BATTERY_HEALTH_PCT: _number(50, 100, 1, "%"),
    CONF_CONSUMPTION_KM_PER_KWH: _number(1, 15, 0.1, "km/kWh"),
    CONF_CONSUMPTION_COLD_KM_PER_KWH: _number(1, 15, 0.1, "km/kWh"),
    CONF_CHARGE_EFFICIENCY: _number(0.5, 1, 0.01),
    CONF_CHARGER_MIN_POWER_W: _number(0, 22000, 10, "W"),
    CONF_CHARGER_MAX_POWER_W: _number(1000, 22000, 10, "W"),
    CONF_PHASE_SWITCHING: selector.BooleanSelector(),
    CONF_CHARGER_MIN_POWER_1P_W: _number(0, 7400, 10, "W"),
    CONF_CHARGER_MAX_POWER_1P_W: _number(0, 7400, 10, "W"),
    CONF_SOLAR_SHARE_PCT: _number(0, 100, 5, "%"),
    CONF_SOC_RESERVE_PCT: _number(0, 100, 1, "%"),
    CONF_BASELINE_MODE: selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[BASELINE_ROLLING, BASELINE_FIXED],
            translation_key=CONF_BASELINE_MODE,
        )
    ),
    CONF_BASELINE_WINDOW_MIN: _number(5, 240, 5, "min"),
    CONF_BASELINE_FIXED_W: _number(0, 20000, 10, "W"),
}


# Form order: car, wallbox, solar and house, house baseline.
_FIELD_ORDER = (
    CONF_SOC_ENTITY,
    CONF_BATTERY_CAPACITY_KWH,
    CONF_BATTERY_HEALTH_PCT,
    CONF_CHARGE_LIMIT_ENTITY,
    CONF_CONSUMPTION_KM_PER_KWH,
    CONF_TEMPERATURE_ENTITY,
    CONF_CONSUMPTION_COLD_KM_PER_KWH,
    CONF_SOC_RESERVE_PCT,
    CONF_WALLBOX_POWER_ENTITY,
    CONF_CHARGE_EFFICIENCY,
    CONF_CHARGER_MIN_POWER_W,
    CONF_CHARGER_MAX_POWER_W,
    CONF_PHASE_SWITCHING,
    CONF_CHARGER_MIN_POWER_1P_W,
    CONF_CHARGER_MAX_POWER_1P_W,
    CONF_SOLAR_SHARE_PCT,
    CONF_PV_POWER_ENTITY,
    CONF_HOUSE_LOAD_ENTITY,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_TOMORROW_ENTITY,
    CONF_FORECAST_EXTRA_ENTITIES,
    CONF_BASELINE_MODE,
    CONF_BASELINE_WINDOW_MIN,
    CONF_BASELINE_FIXED_W,
)


def _schema(values: dict[str, Any]) -> vol.Schema:
    """Full settings schema pre-filled with `values`."""
    fields: dict[Any, Any] = {}
    for key in _FIELD_ORDER:
        if key in _REQUIRED_ENTITIES:
            selector_ = _SENSOR_OR_NUMBER if key == CONF_SOC_ENTITY else _SENSOR
            fields[vol.Required(key, default=values.get(key, vol.UNDEFINED))] = (
                selector_
            )
        elif key in _OPTIONAL_ENTITIES:
            selector_ = {
                CONF_CHARGE_LIMIT_ENTITY: _SENSOR_OR_NUMBER,
                CONF_FORECAST_EXTRA_ENTITIES: _SENSORS_MULTI,
                CONF_TEMPERATURE_ENTITY: _TEMPERATURE,
            }.get(key, _SENSOR)
            if values.get(key):
                fields[
                    vol.Optional(key, description={"suggested_value": values[key]})
                ] = selector_
            else:
                fields[vol.Optional(key)] = selector_
        else:
            fields[vol.Required(key, default=values.get(key, DEFAULTS[key]))] = (
                _PARAM_SELECTORS[key]
            )
    return vol.Schema(fields)


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if user_input[CONF_CHARGER_MIN_POWER_W] > user_input[CONF_CHARGER_MAX_POWER_W]:
        errors[CONF_CHARGER_MIN_POWER_W] = "min_above_max"
    if (
        user_input[CONF_PHASE_SWITCHING]
        and user_input[CONF_CHARGER_MIN_POWER_1P_W]
        > user_input[CONF_CHARGER_MAX_POWER_1P_W]
    ):
        errors[CONF_CHARGER_MIN_POWER_1P_W] = "min_above_max"
    return errors


class EvChargePlannerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick source entities and vehicle/charger parameters."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(
                    title="EV Charge Planner", data=user_input
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options flow."""
        return EvChargePlannerOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Trips are subentries."""
        return {SUBENTRY_TRIP: TripSubentryFlow}


class EvChargePlannerOptionsFlow(OptionsFlow):
    """Edit all settings. The entry reloads via its update listener."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                # Keep cleared optional entities as explicit None so they
                # override values stored in entry.data.
                for key in _OPTIONAL_ENTITIES:
                    user_input.setdefault(key, None)
                return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(user_input or entry_config(self.config_entry)),
            errors=errors,
        )


class TripSubentryFlow(ConfigSubentryFlow):
    """Add or edit a trip scenario."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a trip."""
        return await self._async_step_trip("user", user_input, None)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit a trip."""
        return await self._async_step_trip(
            "reconfigure", user_input, self._get_reconfigure_subentry()
        )

    async def _async_step_trip(
        self, step_id: str, user_input: dict[str, Any] | None, subentry: Any
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_TRIP_NAME].strip()
            taken = {
                s.title.casefold()
                for s in self._get_entry().subentries.values()
                if subentry is None or s.subentry_id != subentry.subentry_id
            }
            if not name:
                errors[CONF_TRIP_NAME] = "name_required"
            elif name.casefold() in taken:
                errors[CONF_TRIP_NAME] = "name_exists"
            else:
                data = {
                    CONF_DISTANCE_KM: user_input[CONF_DISTANCE_KM],
                    CONF_ROUND_TRIP: user_input[CONF_ROUND_TRIP],
                }
                if subentry is None:
                    return self.async_create_entry(title=name, data=data)
                return self.async_update_and_abort(
                    self._get_entry(), subentry, title=name, data=data
                )

        defaults: dict[str, Any] = user_input or (
            {CONF_TRIP_NAME: subentry.title, **subentry.data} if subentry else {}
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TRIP_NAME, default=defaults.get(CONF_TRIP_NAME, vol.UNDEFINED)
                ): selector.TextSelector(),
                vol.Required(
                    CONF_DISTANCE_KM,
                    default=defaults.get(CONF_DISTANCE_KM, vol.UNDEFINED),
                ): _number(1, 2000, 1, "km"),
                vol.Required(
                    CONF_ROUND_TRIP, default=defaults.get(CONF_ROUND_TRIP, True)
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)
