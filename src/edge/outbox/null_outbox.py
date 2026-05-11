"""Outbox that discards every event.

Used as the inner target for the **demo** outbox chain: demo events still tee
through ProjectingOutbox (dashboard updates) and AlertingOutbox (alerts work
on demo data too), but the bottom-layer NullOutbox is where SqliteOutbox
would sit — so the sync pipeline never sees demo events and they never reach
the cloud.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from edge.domain.events import EventEnvelope, EventType


class NullOutbox:
    async def init(self) -> None:  # noqa: D401
        return None

    async def close(self) -> None:
        return None

    async def put(self, event: EventEnvelope) -> None:  # noqa: ARG002
        return None

    async def peek(
        self, event_type: EventType, limit: int  # noqa: ARG002
    ) -> Sequence[EventEnvelope]:
        return []

    async def ack(self, event_ids: Sequence[UUID]) -> None:  # noqa: ARG002
        return None

    async def nack(self, event_ids: Sequence[UUID]) -> None:  # noqa: ARG002
        return None

    async def pending_count(self) -> int:
        return 0
