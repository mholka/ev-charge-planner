"""Constants for EV Charge Planner."""

from datetime import timedelta

DOMAIN = "ev_charge_planner"
UPDATE_INTERVAL = timedelta(minutes=5)

CONF_SOC_ENTITY = "soc_entity"
CONF_CHARGE_LIMIT_ENTITY = "charge_limit_entity"
CONF_PV_POWER_ENTITY = "pv_power_entity"
CONF_HOUSE_LOAD_ENTITY = "house_load_entity"
CONF_WALLBOX_POWER_ENTITY = "wallbox_power_entity"
CONF_FORECAST_ENTITY = "forecast_entity"
CONF_FORECAST_TOMORROW_ENTITY = "forecast_tomorrow_entity"
CONF_FORECAST_EXTRA_ENTITIES = "forecast_extra_entities"

CONF_BATTERY_CAPACITY_KWH = "battery_capacity_kwh"
CONF_BATTERY_HEALTH_PCT = "battery_health_pct"
CONF_CONSUMPTION_KM_PER_KWH = "consumption_km_per_kwh"
CONF_CHARGE_EFFICIENCY = "charge_efficiency"
CONF_CHARGER_MIN_POWER_W = "charger_min_power_w"
CONF_CHARGER_MAX_POWER_W = "charger_max_power_w"
# Shown as "Minimum battery level"; the key predates the rename.
CONF_SOC_RESERVE_PCT = "soc_reserve_pct"
CONF_PHASE_SWITCHING = "phase_switching"
CONF_SOLAR_SHARE_PCT = "solar_share_pct"
CONF_CHARGER_MIN_POWER_1P_W = "charger_min_power_1p_w"
CONF_CHARGER_MAX_POWER_1P_W = "charger_max_power_1p_w"

CONF_BASELINE_MODE = "baseline_mode"
CONF_BASELINE_WINDOW_MIN = "baseline_window_min"
CONF_BASELINE_FIXED_W = "baseline_fixed_w"
BASELINE_ROLLING = "rolling"
BASELINE_FIXED = "fixed"

SUBENTRY_TRIP = "trip"
CONF_TRIP_NAME = "name"
CONF_DISTANCE_KM = "distance_km"
CONF_ROUND_TRIP = "round_trip"

SCENARIO_FULL = "full"
SCENARIO_QUICK_TRIP = "quick_trip"
# Scenarios whose entities live on the main "EV" device.
MAIN_SCENARIOS = (SCENARIO_FULL, SCENARIO_QUICK_TRIP)

DEFAULTS = {
    CONF_BATTERY_CAPACITY_KWH: 75.0,
    CONF_BATTERY_HEALTH_PCT: 100.0,
    CONF_CONSUMPTION_KM_PER_KWH: 5.0,
    CONF_CHARGE_EFFICIENCY: 0.90,
    CONF_CHARGER_MIN_POWER_W: 4100.0,
    CONF_CHARGER_MAX_POWER_W: 11000.0,
    CONF_SOC_RESERVE_PCT: 10.0,
    CONF_PHASE_SWITCHING: False,
    CONF_SOLAR_SHARE_PCT: 100.0,
    CONF_CHARGER_MIN_POWER_1P_W: 1380.0,
    CONF_CHARGER_MAX_POWER_1P_W: 3680.0,
    CONF_BASELINE_MODE: BASELINE_ROLLING,
    CONF_BASELINE_WINDOW_MIN: 30,
    CONF_BASELINE_FIXED_W: 500.0,
}
