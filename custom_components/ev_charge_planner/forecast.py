"""PV forecast adapters. No Home Assistant imports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
import itertools
from statistics import median
from typing import Any

from .planner import Slot

SOLCAST_DEFAULT_PERIOD = timedelta(minutes=30)


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else None
    return None


def parse_solcast(attributes: Mapping[str, Any]) -> list[Slot]:
    """Build slots from a Solcast sensor's `detailedForecast` (or `detailedHourly`).

    Items look like {"period_start": datetime|iso str, "pv_estimate": kW}.
    Invalid items are skipped. The period length is inferred from the data.
    """
    items = attributes.get("detailedForecast") or attributes.get("detailedHourly")
    if not isinstance(items, Sequence) or isinstance(items, str):
        return []

    points: list[tuple[datetime, float]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        start = _parse_time(item.get("period_start"))
        try:
            pv_kw = float(item.get("pv_estimate"))
        except (TypeError, ValueError):
            continue
        if start is not None:
            points.append((start, max(0.0, pv_kw) * 1000))

    points.sort(key=lambda p: p[0])
    diffs = [b[0] - a[0] for a, b in itertools.pairwise(points) if b[0] > a[0]]
    period = median(diffs) if diffs else SOLCAST_DEFAULT_PERIOD
    return [Slot(start, start + period, pv_w) for start, pv_w in points]


def merge_slots(*slot_lists: Sequence[Slot]) -> list[Slot]:
    """Concatenate slot lists (e.g. today + tomorrow), dropping duplicate starts."""
    by_start: dict[datetime, Slot] = {}
    for slots in slot_lists:
        for slot in slots:
            by_start.setdefault(slot.start, slot)
    return [by_start[k] for k in sorted(by_start)]
