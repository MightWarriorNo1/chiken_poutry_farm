"""Heartbeat pipeline: periodically reports device health to the cloud."""

from __future__ import annotations

from datetime import datetime, timezone

import anyio
import structlog

from edge.domain.device import (
    DeviceHeartbeat,
    DeviceStatus,
)
from edge.domain.events import EventEnvelope, EventType
from edge.outbox.outbox import Outbox

log = structlog.get_logger(__name__)


class HeartbeatPipeline:
    def __init__(
        self,
        device_id: str,
        software_version: str,
        outbox: Outbox,
        interval_seconds: int = 30,
    ) -> None:
        self._device_id = device_id
        self._software_version = software_version
        self._outbox = outbox
        self._interval = interval_seconds

    async def run(self) -> None:
        while True:
            try:
                pending = await self._outbox.pending_count()
                hb = DeviceHeartbeat(
                    device_id=self._device_id,
                    reported_at=datetime.now(timezone.utc),
                    status=DeviceStatus.HEALTHY,
                    software_version=self._software_version,
                    outbox_pending=pending,
                )
                await self._outbox.put(
                    EventEnvelope(
                        event_type=EventType.DEVICE_HEARTBEAT,
                        payload=hb.model_dump(mode="json"),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("heartbeat.build.failed", error=str(exc))
            await anyio.sleep(self._interval)
