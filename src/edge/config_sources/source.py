"""Port: a source of the rolled-up `EdgeConfig` for this device.

Adapters live alongside (http, yaml). Returning `None` means "no change since last
fetch" — the supervisor must keep current state.
"""

from __future__ import annotations

from typing import Any, Protocol


class EdgeConfigSource(Protocol):
    """Polled by ConfigPipeline. Implementations decide their own change detection."""

    async def fetch(self) -> dict[str, Any] | None: ...
