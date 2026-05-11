"""AlertEngine — runs the configured rules against incoming events + on a tick.

Wired in via [`AlertingOutbox`](alerting_outbox.py) which calls `on_event` after
every successful `outbox.put`. The engine writes alerts back to the same outbox
so they sync to the cloud through the same pipeline as everything else.

Rules are isolated — an exception in one doesn't disturb others.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone

import anyio
import structlog

from edge.alerts.rule import AlertRule
from edge.domain.alert import Alert
from edge.domain.events import EventEnvelope, EventType
from edge.outbox.outbox import Outbox

log = structlog.get_logger(__name__)

TimeProvider = Callable[[], datetime]


class AlertEngine:
    def __init__(
        self,
        outbox: Outbox,
        rules: Sequence[AlertRule],
        tick_interval_seconds: float = 10.0,
        time_provider: TimeProvider = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._outbox = outbox
        self._rules = list(rules)
        self._tick_interval = tick_interval_seconds
        self._now = time_provider

    @property
    def rules(self) -> list[AlertRule]:
        return list(self._rules)

    async def on_event(self, event: EventEnvelope) -> None:
        """Subscribe this to the outbox wrapper. Never raises."""
        # Don't loop on our own output.
        if event.event_type == EventType.ALERT:
            return
        for rule in self._rules:
            try:
                alerts = await rule.on_event(event)
            except Exception as exc:  # noqa: BLE001
                log.exception("alert.rule.event.failed", rule=rule.name, error=str(exc))
                continue
            for alert in alerts:
                await self._emit(alert)

    async def run(self) -> None:
        """Periodic tick for time-based rules (e.g. camera-offline detection)."""
        while True:
            await anyio.sleep(self._tick_interval)
            now = self._now()
            for rule in self._rules:
                try:
                    alerts = await rule.tick(now)
                except Exception as exc:  # noqa: BLE001
                    log.exception("alert.rule.tick.failed", rule=rule.name, error=str(exc))
                    continue
                for alert in alerts:
                    await self._emit(alert)

    async def emit(self, alert: Alert) -> None:
        """Public hook for callers that need to inject an alert directly
        (e.g. the InferenceSupervisor when a model swap fails)."""
        await self._emit(alert)

    async def _emit(self, alert: Alert) -> None:
        envelope = EventEnvelope(
            event_type=EventType.ALERT,
            payload=alert.model_dump(mode="json"),
        )
        await self._outbox.put(envelope)
        log.info(
            "alert.raised",
            type=alert.alert_type.value,
            severity=alert.severity.value,
            source=alert.source.value,
            key=alert.correlation_key,
        )
