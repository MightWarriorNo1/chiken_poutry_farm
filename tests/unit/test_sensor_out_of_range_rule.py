"""SensorOutOfRangeRule — threshold breach + recovery + cooldown."""

from __future__ import annotations

import pytest

from edge.alerts.rules.sensor_out_of_range import SensorOutOfRangeRule
from edge.domain.events import EventEnvelope, EventType


def _reading(sensor_id: str, value: float) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.SENSOR_READING,
        payload={
            "event_id": "00000000-0000-0000-0000-000000000001",
            "device_id": "edge-1",
            "sensor_id": sensor_id,
            "sensor_type": "temperature",
            "value": value,
            "unit": "celsius",
            "recorded_at": "2026-05-11T12:00:00+00:00",
        },
    )


def _sensor_cfg(sensor_id: str, mn: float | None, mx: float | None) -> dict:
    return {
        "sensor_id": sensor_id,
        "sensor_type": "temperature",
        "shed_id": "shed-1",
        "thresholds": {"min": mn, "max": mx},
    }


@pytest.mark.asyncio
async def test_no_alert_when_within_range() -> None:
    rule = SensorOutOfRangeRule(
        device_id="edge-1", sensor_configs=[_sensor_cfg("t1", 18, 30)]
    )
    assert (await rule.on_event(_reading("t1", 24.0))) == []


@pytest.mark.asyncio
async def test_alert_when_above_max() -> None:
    rule = SensorOutOfRangeRule(
        device_id="edge-1", sensor_configs=[_sensor_cfg("t1", 18, 30)]
    )
    alerts = await rule.on_event(_reading("t1", 35.5))
    assert len(alerts) == 1
    assert alerts[0].alert_type.value == "sensor_out_of_range"
    assert alerts[0].sensor_id == "t1"
    assert alerts[0].shed_id == "shed-1"
    assert alerts[0].metrics["direction"] == "high"
    assert alerts[0].severity.value == "high"


@pytest.mark.asyncio
async def test_alert_when_below_min() -> None:
    rule = SensorOutOfRangeRule(
        device_id="edge-1", sensor_configs=[_sensor_cfg("t1", 18, 30)]
    )
    alerts = await rule.on_event(_reading("t1", 12.0))
    assert len(alerts) == 1
    assert alerts[0].metrics["direction"] == "low"
    assert alerts[0].severity.value == "medium"


@pytest.mark.asyncio
async def test_cooldown_suppresses_repeats() -> None:
    rule = SensorOutOfRangeRule(
        device_id="edge-1",
        sensor_configs=[_sensor_cfg("t1", 18, 30)],
        cooldown_seconds=999.0,
    )
    first = await rule.on_event(_reading("t1", 35))
    second = await rule.on_event(_reading("t1", 36))
    third = await rule.on_event(_reading("t1", 37))
    assert len(first) == 1
    assert len(second) == 0
    assert len(third) == 0


@pytest.mark.asyncio
async def test_recovery_clears_cooldown() -> None:
    """Once the reading returns to range, the next breach should fire immediately."""
    rule = SensorOutOfRangeRule(
        device_id="edge-1",
        sensor_configs=[_sensor_cfg("t1", 18, 30)],
        cooldown_seconds=999.0,
    )
    breach = await rule.on_event(_reading("t1", 35))
    recovered = await rule.on_event(_reading("t1", 24))
    again = await rule.on_event(_reading("t1", 36))
    assert len(breach) == 1
    assert len(recovered) == 0
    assert len(again) == 1


@pytest.mark.asyncio
async def test_unknown_sensor_is_ignored() -> None:
    rule = SensorOutOfRangeRule(
        device_id="edge-1", sensor_configs=[_sensor_cfg("known", 0, 10)]
    )
    assert (await rule.on_event(_reading("unknown", 999))) == []


@pytest.mark.asyncio
async def test_update_sensors_swaps_thresholds() -> None:
    rule = SensorOutOfRangeRule(device_id="edge-1")
    assert (await rule.on_event(_reading("t1", 100))) == []
    rule.update_sensors([_sensor_cfg("t1", 0, 50)])
    alerts = await rule.on_event(_reading("t1", 100))
    assert len(alerts) == 1
