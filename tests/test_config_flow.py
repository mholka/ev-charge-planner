"""Config, options and trip subentry flow tests."""

from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_charge_planner.const import (
    CONF_BASELINE_FIXED_W,
    CONF_BASELINE_MODE,
    CONF_CHARGE_LIMIT_ENTITY,
    CONF_CHARGER_MAX_POWER_1P_W,
    CONF_CHARGER_MIN_POWER_1P_W,
    CONF_CHARGER_MIN_POWER_W,
    CONF_DISTANCE_KM,
    CONF_PHASE_SWITCHING,
    CONF_ROUND_TRIP,
    CONF_TRIP_NAME,
    DOMAIN,
    SUBENTRY_TRIP,
)

from .common import CONFIG, set_sources


async def test_user_flow(hass: HomeAssistant) -> None:
    set_sources(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**CONFIG, CONF_CHARGER_MIN_POWER_W: 20000}
    )
    assert result["errors"] == {CONF_CHARGER_MIN_POWER_W: "min_above_max"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **CONFIG,
            CONF_PHASE_SWITCHING: True,
            CONF_CHARGER_MIN_POWER_1P_W: 4000,
            CONF_CHARGER_MAX_POWER_1P_W: 3000,
        },
    )
    assert result["errors"] == {CONF_CHARGER_MIN_POWER_1P_W: "min_above_max"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], CONFIG)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == CONFIG


async def test_single_instance(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, data=CONFIG).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow(hass: HomeAssistant) -> None:
    set_sources(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    user_input = {k: v for k, v in CONFIG.items() if k != CONF_CHARGE_LIMIT_ENTITY}
    user_input |= {CONF_BASELINE_MODE: "fixed", CONF_BASELINE_FIXED_W: 800.0}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_CHARGE_LIMIT_ENTITY] is None
    assert entry.runtime_data.conf[CONF_BASELINE_FIXED_W] == 800.0
    assert hass.states.get("sensor.ev_house_baseline").state == "800"


async def test_trip_subentry_add_and_reconfigure(hass: HomeAssistant) -> None:
    set_sources(hass, soc=50)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=CONFIG,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_DISTANCE_KM: 50, CONF_ROUND_TRIP: True},
                subentry_type=SUBENTRY_TRIP,
                title="Office",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TRIP), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_TRIP_NAME: "office", CONF_DISTANCE_KM: 10, CONF_ROUND_TRIP: False},
    )
    assert result["errors"] == {CONF_TRIP_NAME: "name_exists"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_TRIP_NAME: "Vienna", CONF_DISTANCE_KM: 150, CONF_ROUND_TRIP: True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    # New trip entities appear without restart: 150 km × 2 / 5 / 75 kWh = 80 % + 10 %
    state = hass.states.get("sensor.ev_vienna_energy_needed")
    assert state is not None
    assert float(state.attributes["target_soc"]) == 90.0

    office_id = next(s for s, e in entry.subentries.items() if e.title == "Office")
    result = await entry.start_subentry_reconfigure_flow(hass, office_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_TRIP_NAME: "Office", CONF_DISTANCE_KM: 75, CONF_ROUND_TRIP: False},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    # 75 km / 5 / 75 kWh = 20 % + 10 % reserve
    state = hass.states.get("sensor.ev_office_energy_needed")
    assert float(state.attributes["target_soc"]) == 30.0
