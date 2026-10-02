"""Translations shipped for custom integrations must be fully resolved."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
COMPONENT = ROOT / "custom_components" / "ev_charge_planner"
sys.path.insert(0, str(ROOT / "scripts"))

from gen_translations import resolve  # noqa: E402


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_en_json_is_resolved_strings_json() -> None:
    en = _load(COMPONENT / "translations" / "en.json")
    assert "[%key:" not in json.dumps(en)
    # Regenerate with: python scripts/gen_translations.py
    assert en == resolve(_load(COMPONENT / "strings.json"))


def test_options_form_matches_setup_form() -> None:
    strings = _load(COMPONENT / "strings.json")
    user = strings["config"]["step"]["user"]
    init = strings["options"]["step"]["init"]
    assert init["data"].keys() == user["data"].keys()
    assert init["data_description"].keys() == user["data_description"].keys()
