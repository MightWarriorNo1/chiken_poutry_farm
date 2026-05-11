"""Outbox decorator that tees every put into the dashboard read model + event bus.

Composes around the existing `AlertingOutbox` exactly the way `AlertingOutbox`
composes around `SqliteOutbox` — pipelines see a regular `Outbox`. Errors in the
read-model side are logged and swallowed so a projection bug can never break
event persistence (the durability contract belongs to the inner outbox).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import structlog

from edge.dashboard.event_bus import EventBus
from edge.dashboard.read_model import ReadModel
from edge.domain.events import EventEnvelope, EventType
from edge.outbox.outbox import Outbox

log = structlog.get_logger(__name__)


class ProjectingOutbox:
    """Wraps an Outbox; on every successful put, updates the ReadModel and
    publishes to the EventBus."""

    def __init__(
        self,
        inner: Outbox,
        read_model: ReadModel,
        event_bus: EventBus,
    ) -> None:
        self._inner = inner
        self._read_model = read_model
        self._event_bus = event_bus

    async def init(self) -> None:
        await self._inner.init()

    async def close(self) -> None:
        await self._inner.close()

    async def put(self, event: EventEnvelope) -> None:
        await self._inner.put(event)
        # Project + publish *after* persistence; both wrapped so a single bug
        # can't take down the pipeline.
        try:
            await self._read_model.apply(event)
        except Exception as exc:  # noqa: BLE001
            log.exception("dashboard.projection.failed", error=str(exc))
        try:
            await self._event_bus.publish(event)
        except Exception as exc:  # noqa: BLE001
            log.exception("dashboard.event_bus.publish.failed", error=str(exc))

    async def peek(self, event_type: EventType, limit: int) -> Sequence[EventEnvelope]:
        return await self._inner.peek(event_type, limit)

    async def ack(self, event_ids: Sequence[UUID]) -> None:
        await self._inner.ack(event_ids)

    async def nack(self, event_ids: Sequence[UUID]) -> None:
        await self._inner.nack(event_ids)

    async def pending_count(self) -> int:
        return await self._inner.pending_count()
