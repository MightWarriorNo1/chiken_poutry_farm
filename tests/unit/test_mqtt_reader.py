"""MqttSensorReader: message parsing + bridge into the async stream.

These tests exercise `_handle_message` directly so they don't require a real
broker. The integration test in tests/integration/test_mqtt_to_outbox.py covers
the live paho path.
"""

from __future__ import annotations

import json

import anyio
import pytest

from edge.config import MqttSettings
from edge.domain.reading import SensorQuality, SensorType
from edge.sensors.mqtt_reader import MqttSensorReader
from edge.sensors.spec import SensorSpec


def _reader(*specs: SensorSpec) -> MqttSensorReader:
    return MqttSensorReader(
        device_id="edge-1",
        broker=MqttSettings(),
        sensors=specs,
    )


@pytest.mark.asyncio
async def test_handle_known_topic_emits_reading() -> None:
    spec = SensorSpec(
        sensor_id="t1",
        sensor_type=SensorType.TEMPERATURE,
        unit="celsius",
        shed_id="shed-1",
        source={"protocol": "mqtt", "topic": "p/t1"},
    )
    reader = _reader(spec)
    reading = reader._handle_message("p/t1", json.dumps({"value": 24.5}).encode())

    assert reading is not None
    assert reading.value == 24.5
    assert reading.sensor_id == "t1"
    assert reading.sensor_type == SensorType.TEMPERATURE
    assert reading.unit == "celsius"  # from spec, not payload
    assert reading.shed_id == "shed-1"
    assert reading.quality == SensorQuality.GOOD


@pytest.mark.asyncio
async def test_unknown_topic_returns_none() -> None:
    reader = _reader(
        SensorSpec(
            sensor_id="t1",
            sensor_type=SensorType.TEMPERATURE,
            source={"protocol": "mqtt", "topic": "known"},
        )
    )
    assert reader._handle_message("not/registered", b'{"value": 1}') is None


@pytest.mark.asyncio
async def test_malformed_payload_returns_none() -> None:
    reader = _reader(
        SensorSpec(
            sensor_id="t1",
            sensor_type=SensorType.TEMPERATURE,
            source={"protocol": "mqtt", "topic": "p/t1"},
        )
    )
    assert reader._handle_message("p/t1", b"not json") is None
    assert reader._handle_message("p/t1", b'{"no_value_field": true}') is None
    assert reader._handle_message("p/t1", b'{"value": "not a number"}') is None


@pytest.mark.asyncio
async def test_raw_number_payload_is_accepted() -> None:
    reader = _reader(
        SensorSpec(
            sensor_id="t1",
            sensor_type=SensorType.TEMPERATURE,
            source={"protocol": "mqtt", "topic": "p/t1"},
        )
    )
    reading = reader._handle_message("p/t1", b"23.7")
    assert reading is not None
    assert reading.value == 23.7


@pytest.mark.asyncio
async def test_handled_messages_flow_through_readings_stream() -> None:
    reader = _reader(
        SensorSpec(
            sensor_id="t1",
            sensor_type=SensorType.TEMPERATURE,
            unit="celsius",
            source={"protocol": "mqtt", "topic": "p/t1"},
        )
    )

    reader._handle_message("p/t1", json.dumps({"value": 22.0}).encode())
    reader._handle_message("p/t1", json.dumps({"value": 22.5}).encode())

    collected = []

    async def collect() -> None:
        async for r in reader.readings():
            collected.append(r.value)
            if len(collected) == 2:
                await reader.stop()
                return

    with anyio.move_on_after(1.0):
        await collect()

    assert collected == [22.0, 22.5]
