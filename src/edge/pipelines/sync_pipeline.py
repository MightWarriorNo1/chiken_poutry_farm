"""Sync pipeline: drain outbox → cloud, in batches per event type.

Strict FIFO per type. On transport failure: nack (increment attempts), back off,
retry on next tick. The outbox keeps the data durable until acked.
"""

from __future__ import annotations

import anyio
import structlog

from edge.domain.events import EventType
from edge.outbox.outbox import Outbox
from edge.sync.sync import CloudSync

log = structlog.get_logger(__name__)


class SyncPipeline:
    def __init__(
        self,
        outbox: Outbox,
        cloud: CloudSync,
        batch_size: int = 50,
        flush_interval_seconds: int = 5,
    ) -> None:
        self._outbox = outbox
        self._cloud = cloud
        self._batch_size = batch_size
        self._flush_interval = flush_interval_seconds

    async def run(self) -> None:
        while True:
            for event_type in EventType:
                await self._drain_one_type(event_type)
            await anyio.sleep(self._flush_interval)

    async def _drain_one_type(self, event_type: EventType) -> None:
        events = await self._outbox.peek(event_type, self._batch_size)
        if not events:
            return
        try:
            await self._cloud.send_batch(event_type, events)
            await self._outbox.ack([e.event_id for e in events])
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "sync.batch.failed",
                event_type=event_type.value,
                count=len(events),
                error=str(exc),
            )
            await self._outbox.nack([e.event_id for e in events])
