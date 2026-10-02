"""Write translations/en.json from strings.json with [%key:...%] references resolved.

Home Assistant resolves these references only when building core integrations;
custom integrations load translations/en.json as is.

Usage: python scripts/gen_translations.py
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

COMPONENT = Path(__file__).parent.parent / "custom_components" / "ev_charge_planner"
REFERENCE = re.compile(r"\[%key:([a-z0-9_:]+)%\]")


def resolve(strings: dict[str, Any]) -> dict[str, Any]:
    """Copy of `strings` with every [%key:component::<domain>::...%] replaced."""

    def lookup(key: str) -> str:
        parts = key.split("::")
        if parts[0] != "component":
            raise ValueError(f"Unsupported reference: {key}")
        node: Any = strings
        for part in parts[2:]:
            node = node[part]
        if not isinstance(node, str):
            raise ValueError(f"Reference doesn't point to a string: {key}")
        return substitute(node)

    def substitute(value: str) -> str:
        return REFERENCE.sub(lambda m: lookup(m.group(1)), value)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, str):
            return substitute(node)
        return node

    return walk(strings)


def main() -> None:
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    (COMPONENT / "translations" / "en.json").write_text(
        json.dumps(resolve(strings), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
