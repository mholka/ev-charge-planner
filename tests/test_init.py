"""Setup, entities and deadline tests."""

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_charge_planner.const import (
    CONF_DISTANCE_KM,
    CONF_ROUND_TRIP,
    DOMAIN,
    SUBENTRY_TRIP,
)

from .common import CONFIG, ENTITIES, set_sources


async def _setup(
    hass: HomeAssistant,
    trips: dict[str, float] | None = None,
    extra: dict | None = None,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**CONFIG, **(extra or {})},
        subentries_data=[
            ConfigSubentryData(
                data={CONF_DISTANCE_KM: km, CONF_ROUND_TRIP: True},
                subentry_type=SUBENTRY_TRIP,
                title=name,
                unique_id=None,
            )
            for name, km in (trips or {}).items()
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    set_sources(hass, soc=50, limit=80)
    entry = await _setup(hass, {"Office": 20})
    assert entry.state is ConfigEntryState.LOADED

    # (80 - 50) % of 75 kWh / 0.9
    assert float(
        hass.states.get("sensor.ev_full_energy_needed").state
    ) == pytest.approx(25.0)
    eta = dt_util.parse_datetime(hass.states.get("sensor.ev_full_eta_grid").state)
    assert abs(eta - dt_util.utcnow() - (timedelta(hours=25 / 11))) <= timedelta(
        minutes=1
    )
    assert hass.states.get("sensor.ev_full_eta_pv").state == "unknown"  # no PV
    assert hass.states.get("sensor.ev_full_charge_time_pv").state == "unknown"
    grid_time = hass.states.get("sensor.ev_full_charge_time_grid")
    assert float(grid_time.state) == pytest.approx(25 / 11 * 60, abs=0.2)
    assert grid_time.attributes["unit_of_measurement"] == "min"
    forecast = hass.states.get("sensor.ev_pv_surplus_forecast")
    assert forecast.state == "0.0"
    assert forecast.attributes["forecast_slots"] == 48
    assert forecast.attributes["entities_without_data"] == []
    assert hass.states.get("binary_sensor.ev_full_ready").state == "off"
    # Office: 40 km / 5 / 75 = 10.7 % + 10 % reserve < 50 % SoC
    assert hass.states.get("binary_sensor.ev_office_ready").state == "on"
    assert hass.states.get("sensor.ev_office_energy_needed").state == "0.0"
    assert hass.states.get("select.ev_deadline_scenario").attributes["options"] == [
        "Full",
        "Office",
    ]

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_soc_unavailable_retries(hass: HomeAssistant) -> None:
    set_sources(hass)
    hass.states.async_set(ENTITIES["soc_entity"], "unavailable")
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_refresh_on_soc_change(hass: HomeAssistant) -> None:
    set_sources(hass, soc=50, limit=80)
    await _setup(hass)
    hass.states.async_set(ENTITIES["soc_entity"], "80")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.ev_full_ready").state == "on"
    assert hass.states.get("sensor.ev_full_energy_needed").state == "0.0"


async def test_pv_eta_with_surplus(hass: HomeAssistant) -> None:
    set_sources(hass, soc=50, limit=80, pv_kw=8.0)
    await _setup(hass)
    # 7.5 kW surplus (8 kW PV - 500 W fixed-fallback/rolling baseline) -> 25 / 7.5 h
    eta = dt_util.parse_datetime(hass.states.get("sensor.ev_full_eta_pv").state)
    assert abs(eta - dt_util.utcnow() - (timedelta(hours=25 / 7.5))) <= timedelta(
        minutes=2
    )


async def test_pv_charge_time_extrapolated_and_extra_days(hass: HomeAssistant) -> None:
    set_sources(hass, soc=10, limit=100, pv_kw=5.5)
    # Forecast covers 24 h from the top of the hour; 5 kW surplus -> 120 kWh
    # would be enough, so limit the horizon to 2 slots to force extrapolation.
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    forecast = [
        {"period_start": start + timedelta(minutes=30 * i), "pv_estimate": 5.5}
        for i in range(4)
    ]
    hass.states.async_set(
        ENTITIES["forecast_entity"], "1", {"detailedForecast": forecast}
    )
    hass.states.async_set("sensor.solcast_day_3", "1", {})
    await _setup(hass, extra={"forecast_extra_entities": ["sensor.solcast_day_3"]})

    # 90 % of 75 kWh / 0.9 = 75 kWh at 5 kW = 15 h of PV charging
    state = hass.states.get("sensor.ev_full_charge_time_pv")
    assert float(state.state) == pytest.approx(15 * 60, abs=1)
    assert state.attributes["extrapolated"] is True
    assert state.attributes["done_at"] is None
    assert hass.states.get("sensor.ev_pv_surplus_forecast").attributes[
        "entities_without_data"
    ] == ["sensor.solcast_day_3"]


@pytest.mark.parametrize(("switching", "has_eta"), [(False, False), (True, True)])
async def test_pv_eta_phase_switching(
    hass: HomeAssistant, switching: bool, has_eta: bool
) -> None:
    # 3.5 kW PV - 500 W baseline = 3 kW: only usable on one phase
    set_sources(hass, soc=70, limit=80, pv_kw=3.5)
    await _setup(hass, extra={"phase_switching": switching})
    state = hass.states.get("sensor.ev_full_eta_pv").state
    assert (state != "unknown") is has_eta


async def test_deadline(hass: HomeAssistant) -> None:
    set_sources(hass, soc=50, limit=80)
    await _setup(hass)
    assert hass.states.get("sensor.ev_latest_grid_start").state == "unknown"

    deadline = dt_util.utcnow().replace(microsecond=0) + timedelta(hours=6)
    await hass.services.async_call(
        "datetime",
        "set_value",
        {"entity_id": "datetime.ev_deadline", "datetime": deadline},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert float(
        hass.states.get("sensor.ev_deadline_grid_topup").state
    ) == pytest.approx(25.0)
    start = dt_util.parse_datetime(hass.states.get("sensor.ev_latest_grid_start").state)
    assert abs(start - (deadline - timedelta(hours=25 / 11))) <= timedelta(minutes=1)
    assert hass.states.get("binary_sensor.ev_deadline_at_risk").state == "off"

    await hass.services.async_call(
        "datetime",
        "set_value",
        {
            "entity_id": "datetime.ev_deadline",
            "datetime": dt_util.utcnow() + timedelta(hours=1),
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.ev_deadline_at_risk").state == "on"
