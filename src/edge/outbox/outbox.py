"""Port: durable event queue.

Concrete impl in `sqlite_outbox.py`. Production may swap to RocksDB/LMDB but the
queue contract stays identical.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from edge.domain.events import EventEnvelope, EventType


class Outbox(Protocol):
    async def init(self) -> None: ...

    async def put(self, event: EventEnvelope) -> None: ...

    async def peek(
        self, event_type: EventType, limit: int
    ) -> Sequence[EventEnvelope]: ...

    async def ack(self, event_ids: Sequence[UUID]) -> None: ...

    async def nack(self, event_ids: Sequence[UUID]) -> None:
        """Increment attempt counter — useful for backoff / DLQ later."""

    async def pending_count(self) -> int: ...

    async def close(self) -> None: ...
