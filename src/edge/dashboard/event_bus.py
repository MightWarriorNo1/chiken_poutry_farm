"""In-process pub/sub used by the SSE endpoint.

Subscribers each get a bounded queue. If a subscriber is too slow, **its** events
are dropped — publishers are never blocked. This matters because the publisher
is on the hot path of every camera frame / sensor reading.

The bus is intentionally tiny (no topic filtering, no replay). Anything fancier
can read from the SQLite projection.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import structlog
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from edge.domain.events import EventEnvelope

log = structlog.get_logger(__name__)


class EventBus:
    def __init__(self, max_queue: int = 100) -> None:
        self._max_queue = max_queue
        self._subscribers: list[MemoryObjectSendStream[EventEnvelope]] = []
        self._lock = anyio.Lock()

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[MemoryObjectReceiveStream[EventEnvelope]]:
        send, recv = anyio.create_memory_object_stream[EventEnvelope](self._max_queue)
        async with self._lock:
            self._subscribers.append(send)
        try:
            yield recv
        finally:
            async with self._lock:
                if send in self._subscribers:
                    self._subscribers.remove(send)
            await send.aclose()
            await recv.aclose()

    async def publish(self, event: EventEnvelope) -> None:
        # Snapshot under lock; deliver outside lock so a slow subscriber can't
        # stall the whole bus.
        async with self._lock:
            subs = list(self._subscribers)
        for s in subs:
            try:
                s.send_nowait(event)
            except anyio.WouldBlock:
                log.debug("dashboard.event_bus.dropped", reason="subscriber_full")
            except anyio.BrokenResourceError:
                # Subscriber's recv was closed; they'll be unregistered in their
                # own `subscribe()` finally block. Ignore here.
                pass

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
