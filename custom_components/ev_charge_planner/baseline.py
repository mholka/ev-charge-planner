"""House load baseline (time-weighted rolling average). No Home Assistant imports."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta


class RollingAverage:
    """Time-weighted average of a step signal over a sliding window."""

    def __init__(self, window: timedelta) -> None:
        self.window = window
        self._samples: deque[tuple[datetime, float]] = deque()

    def add(self, when: datetime, value: float) -> None:
        """Record that the signal changed to `value` at `when`."""
        if self._samples and when < self._samples[-1][0]:
            return
        self._samples.append((when, value))

    def mean(self, now: datetime) -> float | None:
        """Average over [now - window, now]; None without samples."""
        start = now - self.window
        # Keep the last sample before the window: it defines the value at `start`.
        while len(self._samples) > 1 and self._samples[1][0] <= start:
            self._samples.popleft()
        if not self._samples:
            return None

        total = 0.0
        weight = 0.0
        samples = list(self._samples)
        for (t, value), nxt in zip(samples, [*samples[1:], None], strict=True):
            seg_start = max(t, start)
            seg_end = min(nxt[0] if nxt else now, now)
            seconds = (seg_end - seg_start).total_seconds()
            if seconds > 0:
                total += value * seconds
                weight += seconds
        if weight == 0:
            return samples[-1][1]
        return total / weight
