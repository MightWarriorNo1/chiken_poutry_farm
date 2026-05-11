"""Port: a source of camera frames.

Adapters: rtsp_source.py (live), file_source.py (dev/demo).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Frame:
    """A single decoded frame plus capture metadata."""

    camera_id: str
    captured_at: datetime
    width: int
    height: int
    image: object  # numpy.ndarray (BGR), kept generic so domain stays numpy-free
    sequence: int = 0


class FrameSource(Protocol):
    """Async generator of frames from a camera-like source."""

    camera_id: str

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    def frames(self) -> AsyncIterator[Frame]: ...
