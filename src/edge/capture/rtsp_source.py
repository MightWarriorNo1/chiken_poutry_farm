"""RTSP frame source backed by OpenCV.

Production note: on Jetson, swap to a GStreamer pipeline for hardware decode.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import anyio

from edge.capture.source import Frame


class RtspFrameSource:
    """OpenCV-based RTSP poller. Reconnects on failure with backoff."""

    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        target_fps: float = 1.0,
        reconnect_seconds: float = 5.0,
    ) -> None:
        self.camera_id = camera_id
        self._url = rtsp_url
        self._target_fps = target_fps
        self._reconnect_seconds = reconnect_seconds
        self._cap: object | None = None
        self._sequence = 0

    async def open(self) -> None:
        # Lazy-import OpenCV so the core runtime stays slim if AI extra isn't installed.
        import cv2  # noqa: PLC0415

        self._cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        if not self._cap.isOpened():
            raise RuntimeError(f"Failed to open RTSP source: {self._url}")

    async def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    async def frames(self) -> AsyncIterator[Frame]:
        import cv2  # noqa: PLC0415, F401

        period = 1.0 / max(self._target_fps, 0.01)
        while True:
            if self._cap is None:
                await self.open()

            assert self._cap is not None
            # OpenCV is sync; offload to a worker thread to avoid blocking the loop.
            ok, image = await anyio.to_thread.run_sync(self._cap.read)  # type: ignore[attr-defined]
            if not ok or image is None:
                await self.close()
                await anyio.sleep(self._reconnect_seconds)
                continue

            self._sequence += 1
            yield Frame(
                camera_id=self.camera_id,
                captured_at=datetime.now(timezone.utc),
                width=int(image.shape[1]),
                height=int(image.shape[0]),
                image=image,
                sequence=self._sequence,
            )
            await anyio.sleep(period)
