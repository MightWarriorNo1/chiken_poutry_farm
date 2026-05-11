"""AlertRule port + a tiny dedup helper used by every rule.

Rules are simple objects with two methods:
  - `on_event(event)`  inspect a freshly-written event, return zero or more Alerts
  - `tick(now)`         called periodically (every N seconds) for time-based rules

Either may return [] if it has nothing to say. The engine catches exceptions per
rule so one bad rule can't break the others.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from edge.domain.alert import Alert
from edge.domain.events import EventEnvelope


class AlertRule(Protocol):
    """All rules implement this. `name` is used in logs and correlation keys."""

    name: str

    async def on_event(self, event: EventEnvelope) -> Sequence[Alert]: ...

    async def tick(self, now: datetime) -> Sequence[Alert]: ...


class RaisedTracker:
    """Suppresses duplicate alerts within a cooldown window.

    Each rule uses one to track per-correlation-key cool-downs. When the
    underlying condition clears, call `reset(key)` so the next breach alerts
    immediately rather than waiting for the cooldown to expire.
    """

    def __init__(self, cooldown_seconds: float = 300.0) -> None:
        self._cooldown = cooldown_seconds
        self._last_raised: dict[str, datetime] = {}

    def should_raise(self, key: str, now: datetime) -> bool:
        last = self._last_raised.get(key)
        if last is None or (now - last).total_seconds() >= self._cooldown:
            self._last_raised[key] = now
            return True
        return False

    def reset(self, key: str) -> None:
        self._last_raised.pop(key, None)
