"""End-to-end: real outbox + engine + wrapper → an Alert is persisted on breach."""

from __future__ import annotations

from pathlib import Path

import pytest

from edge.alerts.alerting_outbox import AlertingOutbox
from edge.alerts.engine import AlertEngine
from edge.alerts.rules.high_huddling import HighHuddlingRule
from edge.alerts.rules.sensor_out_of_range import SensorOutOfRangeRule
from edge.domain.events import EventEnvelope, EventType
from edge.outbox.sqlite_outbox import SqliteOutbox


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sensor_breach_lands_in_outbox(tmp_path: Path) -> None:
    inner = SqliteOutbox(tmp_path / "ob.db")
    await inner.init()
    try:
        rule = SensorOutOfRangeRule(
            device_id="edge-test",
            sensor_configs=[
                {
                    "sensor_id": "t1",
                    "sensor_type": "temperature",
                    "shed_id": "shed-1",
                    "thresholds": {"min": 18, "max": 30},
                }
            ],
        )
        engine = AlertEngine(outbox=inner, rules=[rule])
        outbox = AlertingOutbox(inner=inner, engine=engine)

        # A normal reading (in range) — no alert.
        await outbox.put(EventEnvelope(
            event_type=EventType.SENSOR_READING,
            payload={"sensor_id": "t1", "sensor_type": "temperature",
                     "value": 24.0, "unit": "celsius",
                     "recorded_at": "2026-05-11T12:00:00+00:00",
                     "device_id": "edge-test"},
        ))
        # An out-of-range reading — should generate an alert.
        await outbox.put(EventEnvelope(
            event_type=EventType.SENSOR_READING,
            payload={"sensor_id": "t1", "sensor_type": "temperature",
                     "value": 38.0, "unit": "celsius",
                     "recorded_at": "2026-05-11T12:01:00+00:00",
                     "device_id": "edge-test"},
        ))

        alerts = await inner.peek(EventType.ALERT, 100)
        assert len(alerts) == 1
        payload = alerts[0].payload
        assert payload["alert_type"] == "sensor_out_of_range"
        assert payload["sensor_id"] == "t1"
        assert payload["metrics"]["direction"] == "high"
    finally:
        await inner.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_huddling_breach_lands_in_outbox(tmp_path: Path) -> None:
    inner = SqliteOutbox(tmp_path / "ob.db")
    await inner.init()
    try:
        rule = HighHuddlingRule(
            device_id="edge-test", threshold=0.7, consecutive_frames=2
        )
        engine = AlertEngine(outbox=inner, rules=[rule])
        outbox = AlertingOutbox(inner=inner, engine=engine)

        for score in (0.8, 0.85):
            await outbox.put(EventEnvelope(
                event_type=EventType.HUDDLING_SCORE,
                payload={
                    "device_id": "edge-test", "camera_id": "cam-1",
                    "shed_id": "shed-1", "flock_id": "flock-A",
                    "captured_at": "2026-05-11T12:00:00+00:00",
                    "processed_at": "2026-05-11T12:00:00+00:00",
                    "model_version": "x", "huddling_score": score,
                },
            ))

        alerts = await inner.peek(EventType.ALERT, 100)
        assert len(alerts) == 1
        assert alerts[0].payload["alert_type"] == "high_huddling"
        assert alerts[0].payload["camera_id"] == "cam-1"
    finally:
        await inner.close()
