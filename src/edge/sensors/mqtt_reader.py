"""MQTT sensor reader.

Subscribes to a configured set of `(topic, sensor)` pairs. Each message is
parsed as JSON and bridged into an async stream the SensorPipeline consumes.

Wire format on the topic (per-sensor publisher's responsibility):
    {"value": <number>, "recorded_at": "2026-05-11T...Z", "quality": "good"}

`recorded_at` and `quality` are optional. Anything else in the payload is
ignored. The `unit` and `sensor_type` come from the SensorSpec, not the wire,
so a misconfigured publisher can't change a sensor's identity at runtime.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone

import anyio
import structlog
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from edge.config import MqttSettings
from edge.domain.reading import SensorQuality, SensorReading
from edge.sensors.spec import SensorSpec

log = structlog.get_logger(__name__)


class MqttSensorReader:
    def __init__(
        self,
        device_id: str,
        broker: MqttSettings,
        sensors: Sequence[SensorSpec],
    ) -> None:
        self._device_id = device_id
        self._broker = broker
        self._sensors: tuple[SensorSpec, ...] = tuple(sensors)
        # Topic → spec lookup. Drop sensors without a topic (misconfigured).
        self._by_topic: dict[str, SensorSpec] = {
            str(s.source.get("topic")): s for s in self._sensors if s.source.get("topic")
        }
        self._client: object | None = None
        send: MemoryObjectSendStream[SensorReading]
        recv: MemoryObjectReceiveStream[SensorReading]
        send, recv = anyio.create_memory_object_stream[SensorReading](max_buffer_size=2048)
        self._send = send
        self._recv = recv

    @property
    def topics(self) -> tuple[str, ...]:
        return tuple(self._by_topic)

    async def start(self) -> None:
        try:
            import paho.mqtt.client as mqtt  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "Install the `sensors` extra: pip install -e '.[sensors]'"
            ) from exc

        if not self._by_topic:
            log.warning("mqtt.no_topics", device_id=self._device_id)
            return

        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)  # type: ignore[attr-defined]
        if self._broker.username:
            client.username_pw_set(self._broker.username, self._broker.password or "")
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        client.connect(self._broker.host, self._broker.port, keepalive=60)
        client.loop_start()  # paho's own reconnect loop runs here
        self._client = client
        log.info(
            "mqtt.started",
            host=self._broker.host,
            port=self._broker.port,
            topics=len(self._by_topic),
        )

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

    # ── Test seam: invoked by paho callbacks (sync) but also unit-testable. ──
    def _handle_message(self, topic: str, payload: bytes) -> SensorReading | None:
        spec = self._by_topic.get(topic)
        if spec is None:
            return None  # unknown topic — silently drop

        try:
            data = json.loads(payload.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

        # Accept either {"value": x, ...} or a raw number.
        if isinstance(data, dict):
            try:
                value = float(data["value"])
            except (KeyError, TypeError, ValueError):
                return None
            recorded_at_raw = data.get("recorded_at")
            quality_raw = data.get("quality", "good")
        else:
            try:
                value = float(data)
            except (TypeError, ValueError):
                return None
            recorded_at_raw = None
            quality_raw = "good"

        try:
            recorded_at = (
                datetime.fromisoformat(recorded_at_raw.replace("Z", "+00:00"))
                if recorded_at_raw
                else datetime.now(timezone.utc)
            )
        except (AttributeError, ValueError):
            recorded_at = datetime.now(timezone.utc)

        try:
            quality = SensorQuality(quality_raw)
        except ValueError:
            quality = SensorQuality.GOOD

        reading = SensorReading(
            device_id=self._device_id,
            sensor_id=spec.sensor_id,
            sensor_type=spec.sensor_type,
            shed_id=spec.shed_id,
            zone_id=spec.zone_id,
            value=value,
            unit=spec.unit,
            recorded_at=recorded_at,
            quality=quality,
        )

        try:
            self._send.send_nowait(reading)
        except anyio.WouldBlock:
            log.warning("mqtt.buffer_full", topic=topic)  # in prod: drop oldest
        return reading

    # ── paho callbacks (sync) ─────────────────────────────────────────────
    def _on_connect(
        self,
        client: object,
        _userdata: object,
        _flags: object,
        _reason_code: object,
        _properties: object,
    ) -> None:
        for topic in self._by_topic:
            client.subscribe(topic)  # type: ignore[attr-defined]
        log.info("mqtt.connected", topics=len(self._by_topic))

    def _on_disconnect(
        self,
        _client: object,
        _userdata: object,
        _flags: object,
        reason_code: object,
        _properties: object,
    ) -> None:
        log.warning("mqtt.disconnected", reason=str(reason_code))

    def _on_message(self, _client: object, _userdata: object, msg: object) -> None:
        topic: str = msg.topic  # type: ignore[attr-defined]
        payload: bytes = msg.payload  # type: ignore[attr-defined]
        self._handle_message(topic, payload)
