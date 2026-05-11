"""AlertEngine — routes events to rules, emits alerts to outbox, isolates failures."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import pytest

from edge.alerts.engine import AlertEngine
from edge.domain.alert import Alert, AlertSeverity, AlertSource, AlertType
from edge.domain.events import EventEnvelope, EventType


class _RecordingOutbox:
    """Minimal Outbox implementation that records every put."""

    def __init__(self) -> None:
        self.puts: list[EventEnvelope] = []

    async def init(self) -> None: ...
    async def close(self) -> None: ...
    async def peek(self, t, n): return []
    async def ack(self, ids): ...
    async def nack(self, ids): ...
    async def pending_count(self): return len(self.puts)

    async def put(self, event: EventEnvelope) -> None:
        self.puts.append(event)


class _StubRule:
    name = "stub"

    def __init__(self, alerts_on_event: list[Alert] | None = None,
                 alerts_on_tick: list[Alert] | None = None,
                 raise_on_event: bool = False) -> None:
        self._on_event = alerts_on_event or []
        self._on_tick = alerts_on_tick or []
        self._raise = raise_on_event

    async def on_event(self, _event: EventEnvelope) -> Sequence[Alert]:
        if self._raise:
            raise RuntimeError("boom")
        return self._on_event

    async def tick(self, _now: datetime) -> Sequence[Alert]:
        return self._on_tick


def _alert() -> Alert:
    return Alert(
        device_id="edge-1",
        alert_type=AlertType.CAMERA_OFFLINE,
        severity=AlertSeverity.HIGH,
        source=AlertSource.CAMERA,
        raised_at=datetime.now(timezone.utc),
        message="x",
    )


@pytest.mark.asyncio
async def test_on_event_fans_out_to_rules() -> None:
    a1, a2 = _alert(), _alert()
    outbox = _RecordingOutbox()
    engine = AlertEngine(outbox=outbox, rules=[_StubRule(alerts_on_event=[a1]),
                                                _StubRule(alerts_on_event=[a2])])
    await engine.on_event(EventEnvelope(event_type=EventType.SENSOR_READING, payload={}))
    assert len(outbox.puts) == 2
    assert all(p.event_type == EventType.ALERT for p in outbox.puts)


@pytest.mark.asyncio
async def test_engine_ignores_alert_events_to_avoid_feedback() -> None:
    outbox = _RecordingOutbox()
    triggered: list[EventEnvelope] = []

    class TrackingRule:
        name = "track"

        async def on_event(self, e):
            triggered.append(e)
            return []

        async def tick(self, _now):
            return []

    engine = AlertEngine(outbox=outbox, rules=[TrackingRule()])
    alert_env = EventEnvelope(event_type=EventType.ALERT, payload={})
    sensor_env = EventEnvelope(event_type=EventType.SENSOR_READING, payload={})
    await engine.on_event(alert_env)
    await engine.on_event(sensor_env)
    # Only the non-alert event reached the rule.
    assert len(triggered) == 1
    assert triggered[0].event_type == EventType.SENSOR_READING


@pytest.mark.asyncio
async def test_rule_failure_isolated_from_others() -> None:
    outbox = _RecordingOutbox()
    engine = AlertEngine(outbox=outbox, rules=[
        _StubRule(raise_on_event=True),
        _StubRule(alerts_on_event=[_alert()]),
    ])
    # Must not raise; the other rule's alert must still be emitted.
    await engine.on_event(EventEnvelope(event_type=EventType.SENSOR_READING, payload={}))
    assert len(outbox.puts) == 1


@pytest.mark.asyncio
async def test_emit_writes_to_outbox() -> None:
    outbox = _RecordingOutbox()
    engine = AlertEngine(outbox=outbox, rules=[])
    await engine.emit(_alert())
    assert len(outbox.puts) == 1
    env = outbox.puts[0]
    assert env.event_type == EventType.ALERT
    assert env.payload["alert_type"] == "camera_offline"
