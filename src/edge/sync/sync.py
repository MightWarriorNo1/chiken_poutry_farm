"""Port: cloud sync transport.

PoC adapter is HTTPS+JSON. Production may swap to gRPC streaming; the pipeline
contract is unchanged because the port hides the wire format.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from edge.domain.events import EventEnvelope, EventType


class CloudSync(Protocol):
    async def send_batch(
        self, event_type: EventType, events: Sequence[EventEnvelope]
    ) -> None:
        """Send a batch of events. Raises on transport failure (caller will nack)."""

    async def send_heartbeat(self, payload: dict) -> None: ...

    async def fetch_config(self, etag: str | None = None) -> tuple[dict | None, str | None]:
        """Returns (config, etag). config=None on 304."""
