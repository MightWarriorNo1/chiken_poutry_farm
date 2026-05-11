"""Outbox wrapper that triggers AlertEngine.on_event after every successful put.

Pipelines see this as a regular `Outbox` — no API change. The engine receives
every event the edge produces (except its own alerts, filtered inside the engine
to avoid feedback loops).

The wrapper writes through `inner.put` first; the engine only sees committed
events. If `engine.on_event` raises, we log and swallow — alerting must not
break event persistence.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import structlog

from edge.alerts.engine import AlertEngine
from edge.domain.events import EventEnvelope, EventType
from edge.outbox.outbox import Outbox

log = structlog.get_logger(__name__)


class AlertingOutbox:
    """Decorator over an Outbox that fires the alert engine on every put."""

    def __init__(self, inner: Outbox, engine: AlertEngine) -> None:
        self._inner = inner
        self._engine = engine

    async def init(self) -> None:
        await self._inner.init()

    async def close(self) -> None:
        await self._inner.close()

    async def put(self, event: EventEnvelope) -> None:
        await self._inner.put(event)
        try:
            await self._engine.on_event(event)
        except Exception as exc:  # noqa: BLE001
            # Should never fire — engine catches its own — but be paranoid.
            log.exception("alerts.engine.unhandled", error=str(exc))

    async def peek(self, event_type: EventType, limit: int) -> Sequence[EventEnvelope]:
        return await self._inner.peek(event_type, limit)

    async def ack(self, event_ids: Sequence[UUID]) -> None:
        await self._inner.ack(event_ids)

    async def nack(self, event_ids: Sequence[UUID]) -> None:
        await self._inner.nack(event_ids)

    async def pending_count(self) -> int:
        return await self._inner.pending_count()
