"""End-to-end: MQTT publish → SensorPipeline → outbox.

Uses paho-mqtt directly to simulate a publisher and `_handle_message` to drive
the reader without binding to a real broker. The full broker-backed test runs
under `pytest -m broker` once a Mosquitto container is available.
"""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest

from edge.config import MqttSettings
from edge.domain.events import EventType
from edge.domain.reading import SensorType
from edge.outbox.sqlite_outbox import SqliteOutbox
from edge.pipelines.sensor_pipeline import SensorPipeline
from edge.sensors.mqtt_reader import MqttSensorReader
from edge.sensors.spec import SensorSpec


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mqtt_messages_land_in_outbox(tmp_path: Path) -> None:
    outbox = SqliteOutbox(tmp_path / "ob.db")
    await outbox.init()

    spec = SensorSpec(
        sensor_id="mqtt-temp-1",
        sensor_type=SensorType.TEMPERATURE,
        unit="celsius",
        shed_id="shed-1",
        source={"protocol": "mqtt", "topic": "prosper/sensors/shed-1/temp-1"},
    )
    reader = MqttSensorReader(device_id="edge-test", broker=MqttSettings(), sensors=[spec])
    pipeline = SensorPipeline(reader=reader, outbox=outbox)

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(pipeline.run)

            # Inject 5 messages directly through the reader's bridge — bypasses paho
            # so the test stays hermetic. The integration with real paho is exercised
            # under the broker-backed test (manual run for now).
            for i in range(5):
                reader._handle_message(
                    "prosper/sensors/shed-1/temp-1",
                    json.dumps({"value": 24.0 + i * 0.1}).encode(),
                )
                await anyio.sleep(0.01)

            await anyio.sleep(0.1)
            tg.cancel_scope.cancel()

        events = await outbox.peek(EventType.SENSOR_READING, 100)
        assert len(events) == 5
        values = [e.payload["value"] for e in events]
        assert values == [24.0, 24.1, 24.2, 24.3, 24.4]
        assert events[0].payload["sensor_id"] == "mqtt-temp-1"
        assert events[0].payload["unit"] == "celsius"
        assert events[0].payload["shed_id"] == "shed-1"
    finally:
        await outbox.close()
