"""Per-camera annotated-frame broadcaster.

Receives JPEG bytes from the FramePipeline after inference annotation and
fans them out to any number of MJPEG-stream subscribers without ever
blocking the pipeline. Slow subscribers drop the new frame for themselves
rather than back-pressuring the publisher.

A `latest` snapshot is always retained so newly-connected subscribers see
something immediately instead of waiting for the next publish tick.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream


@dataclass(slots=True)
class _Subscriber:
    send: MemoryObjectSendStream[bytes]
    recv: MemoryObjectReceiveStream[bytes]


class FrameBroadcaster:
    """Latest-frame holder + bounded fan-out to dashboard subscribers.

    Publishers call `publish(jpeg_bytes)` from the FramePipeline hot path.
    Subscribers use::

        async with bcast.subscribe() as recv:
            async for jpeg in recv:
                ...

    Each subscriber has its own bounded queue (`queue_size`). On overflow we
    silently drop the new frame for that subscriber — preserving "show the
    latest state" semantics over "lossless history." The publisher never
    waits.
    """

    def __init__(self, queue_size: int = 4) -> None:
        self._queue_size = queue_size
        self._subscribers: list[_Subscriber] = []
        self._lock = anyio.Lock()
        self._latest: bytes | None = None

    @property
    def has_subscribers(self) -> bool:
        return bool(self._subscribers)

    @property
    def latest(self) -> bytes | None:
        return self._latest

    async def publish(self, jpeg: bytes) -> None:
        self._latest = jpeg
        # Snapshot the subscriber list inside the lock; deliver outside so a
        # slow recv doesn't block other subscribers being woken.
        async with self._lock:
            subs = list(self._subscribers)
        for sub in subs:
            try:
                sub.send.send_nowait(jpeg)
            except anyio.WouldBlock:
                # Subscriber's queue full — they're behind, skip this frame
                # for them. `latest` is still updated so a re-poll sees it.
                pass
            except anyio.BrokenResourceError:
                # Subscriber went away mid-publish; cleanup happens in their
                # own `subscribe()` context manager.
                pass

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[MemoryObjectReceiveStream[bytes]]:
        send, recv = anyio.create_memory_object_stream[bytes](self._queue_size)
        sub = _Subscriber(send=send, recv=recv)
        async with self._lock:
            self._subscribers.append(sub)
            cached = self._latest
        # Prime the new subscriber with the latest cached frame so the
        # connecting client sees something within the first RTT, not after
        # the next inference tick.
        if cached is not None:
            try:
                send.send_nowait(cached)
            except (anyio.WouldBlock, anyio.BrokenResourceError):
                pass
        try:
            yield recv
        finally:
            async with self._lock:
                if sub in self._subscribers:
                    self._subscribers.remove(sub)
            await send.aclose()
            await recv.aclose()
