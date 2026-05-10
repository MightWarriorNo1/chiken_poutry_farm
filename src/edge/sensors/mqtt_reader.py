"""MQTT-based sensor reader.

Subscribes to topics like `<prefix>/<sensor_id>/<sensor_type>` and emits
SensorReading events. Reconnects automatically; survives broker restarts.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from edge.config import MqttSettings
from edge.domain.reading import SensorQuality, SensorReading, SensorType


class MqttSensorReader:
    def __init__(self, device_id: str, settings: MqttSettings) -> None:
        self._device_id = device_id
        self._settings = settings
        self._client: object | None = None
        send: MemoryObjectSendStream[SensorReading]
        recv: MemoryObjectReceiveStream[SensorReading]
        send, recv = anyio.create_memory_object_stream[SensorReading](max_buffer_size=1024)
        self._send = send
        self._recv = recv

    async def start(self) -> None:
        try:
            import paho.mqtt.client as mqtt  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "Install the `sensors` extra: pip install -e '.[sensors]'"
            ) from exc

        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)  # type: ignore[attr-defined]
        if self._settings.username:
            client.username_pw_set(self._settings.username, self._settings.password or "")
        client.on_message = self._on_message
        client.on_connect = self._on_connect
        client.connect(self._settings.host, self._settings.port, keepalive=60)
        client.loop_start()
        self._client = client

    async def stop(self) -> None:
        if self._client is not None:
            self._client.loop_stop()  # type: ignore[attr-defined]
            self._client.disconnect()  # type: ignore[attr-defined]
            self._client = None
        await self._send.aclose()

    async def readings(self) -> AsyncIterator[SensorReading]:
        async with self._recv:
            async for reading in self._recv:
                yield reading

    # ── paho callbacks (sync) ──────────────────────────────────────────────
    def _on_connect(self, client: object, _userdata: object, _flags: object,
                    _reason_code: object, _properties: object) -> None:
        client.subscribe(f"{self._settings.topic_prefix}/+/+")  # type: ignore[attr-defined]

    def _on_message(self, _client: object, _userdata: object, msg: object) -> None:
        try:
            parts = msg.topic.split("/")  # type: ignore[attr-defined]
            sensor_id, sensor_type_raw = parts[-2], parts[-1]
            payload = json.loads(msg.payload.decode())  # type: ignore[attr-defined]
            reading = SensorReading(
                device_id=self._device_id,
                sensor_id=sensor_id,
                sensor_type=SensorType(sensor_type_raw),
                shed_id=payload.get("shed_id"),
                zone_id=payload.get("zone_id"),
                value=float(payload["value"]),
                unit=payload["unit"],
                recorded_at=datetime.fromisoformat(
                    payload.get("recorded_at", datetime.now(timezone.utc).isoformat())
                ),
                quality=SensorQuality(payload.get("quality", "good")),
            )
        except (KeyError, ValueError, TypeError):
            return  # malformed message — drop silently; metric this in prod
        # Bridge sync paho callback → async stream
        try:
            self._send.send_nowait(reading)
        except anyio.WouldBlock:
            pass  # buffer full — drop oldest in prod; fine for PoC
