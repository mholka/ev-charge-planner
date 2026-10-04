"""The notification blueprint must be a valid Home Assistant blueprint."""

from pathlib import Path

from homeassistant.components.automation.config import async_validate_config_item
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.core import HomeAssistant
from homeassistant.util.yaml import load_yaml

BLUEPRINT = (
    Path(__file__).parent.parent
    / "blueprints"
    / "automation"
    / "mholka"
    / "ev_charge_planner_notify.yaml"
)


async def test_blueprint_is_valid(hass: HomeAssistant) -> None:
    blueprint = Blueprint(
        load_yaml(BLUEPRINT), expected_domain="automation", schema=BLUEPRINT_SCHEMA
    )
    inputs = BlueprintInputs(
        blueprint,
        {
            "use_blueprint": {
                "path": "mholka/ev_charge_planner_notify.yaml",
                "input": {"notify_device": "0123456789abcdef"},
            }
        },
    )
    inputs.validate()
    config = inputs.async_substitute()
    config["id"] = "ev_notify"
    # The mobile_app device action can't load in the test environment (it pulls
    # in camera dependencies), so check its shape and validate the rest.
    (action,) = config.pop("actions")
    assert action["domain"] == "mobile_app"
    assert action["type"] == "notify"
    assert action["device_id"] == "0123456789abcdef"
    config["actions"] = []
    validated = await async_validate_config_item(hass, "ev_notify", config)
    assert validated is not None
    assert validated.validation_error is None, validated.validation_error
