"""File-backed frame source for development and demos.

Reads either a video file (via OpenCV) or a directory of images, in a loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

import anyio

from edge.capture.source import Frame


class FileFrameSource:
    """Cycles through an image dir or video file at the configured FPS."""

    def __init__(
        self,
        camera_id: str,
        path: Path,
        target_fps: float = 1.0,
        loop: bool = True,
    ) -> None:
        self.camera_id = camera_id
        self._path = path
        self._target_fps = target_fps
        self._loop = loop
        self._sequence = 0
        self._image_paths: list[Path] = []
        self._cap: object | None = None

    async def open(self) -> None:
        if self._path.is_dir():
            exts = {".jpg", ".jpeg", ".png", ".bmp"}
            self._image_paths = sorted(p for p in self._path.iterdir() if p.suffix.lower() in exts)
            if not self._image_paths:
                raise RuntimeError(f"No images found in {self._path}")
        else:
            import cv2  # noqa: PLC0415

            self._cap = cv2.VideoCapture(str(self._path))
            if not self._cap.isOpened():
                raise RuntimeError(f"Failed to open video: {self._path}")

    async def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    async def frames(self) -> AsyncIterator[Frame]:
        import cv2  # noqa: PLC0415

        period = 1.0 / max(self._target_fps, 0.01)
        idx = 0
        while True:
            image = None
            if self._image_paths:
                image = await anyio.to_thread.run_sync(cv2.imread, str(self._image_paths[idx]))
                idx = (idx + 1) % len(self._image_paths)
                if idx == 0 and not self._loop:
                    return
            elif self._cap is not None:
                ok, image = await anyio.to_thread.run_sync(self._cap.read)  # type: ignore[attr-defined]
                if not ok or image is None:
                    if not self._loop:
                        return
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # type: ignore[attr-defined]
                    continue

            if image is None:
                await anyio.sleep(period)
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
