"""Sensor pipeline: read → outbox."""

from __future__ import annotations

import structlog

from edge.domain.events import EventEnvelope, EventType
from edge.outbox.outbox import Outbox
from edge.sensors.sensor import SensorReader

log = structlog.get_logger(__name__)


class SensorPipeline:
    def __init__(self, reader: SensorReader, outbox: Outbox) -> None:
        self._reader = reader
        self._outbox = outbox

    async def run(self) -> None:
        await self._reader.start()
        try:
            async for reading in self._reader.readings():
                await self._outbox.put(
                    EventEnvelope(
                        event_type=EventType.SENSOR_READING,
                        payload=reading.model_dump(mode="json"),
                    )
                )
        finally:
            await self._reader.stop()
