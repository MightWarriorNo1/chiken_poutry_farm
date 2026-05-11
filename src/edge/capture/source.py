"""Port: a source of camera frames.

Adapters: rtsp_source.py (live), file_source.py (dev/demo).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class Frame:
    """A single decoded frame plus capture metadata.

    `image` is typed loosely (`Any`) so the domain doesn't pull a numpy dependency.
    Adapters that need pixel access (capture, inference) cast to `np.ndarray`.
    """

    camera_id: str
    captured_at: datetime
    width: int
    height: int
    image: Any
    sequence: int = 0


class FrameSource(Protocol):
    """Async generator of frames from a camera-like source."""

    camera_id: str

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    def frames(self) -> AsyncIterator[Frame]: ...
