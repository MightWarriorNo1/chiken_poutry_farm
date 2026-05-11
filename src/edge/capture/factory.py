"""Build a FrameSource from a camera config dict.

Scheme-based dispatch:
  - file://...                 → FileFrameSource (image dir or video)
  - rtsp://..., http(s)://...  → RtspFrameSource (OpenCV-backed)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from edge.capture.source import FrameSource


def build_frame_source(cfg: dict[str, Any], target_fps: float = 1.0) -> FrameSource:
    camera_id: str = cfg["camera_id"]
    source_uri: str = cfg["source_uri"]
    parsed = urlparse(source_uri)

    if parsed.scheme == "file" or (parsed.scheme == "" and source_uri.startswith(("./", "/"))):
        path_str = parsed.path if parsed.scheme == "file" else source_uri
        # Strip leading slash on Windows (`file:///C:/...` → `/C:/...`).
        if len(path_str) > 2 and path_str[0] == "/" and path_str[2] == ":":
            path_str = path_str[1:]
        from edge.capture.file_source import FileFrameSource  # noqa: PLC0415

        # `loop` defaults to True (matches existing dev-frames behaviour) but is
        # turned off for demos so a recorded video runs once and ends, which is
        # what the dashboard's "Demo finished" signal hangs off.
        loop = bool(cfg.get("loop", True))
        return FileFrameSource(
            camera_id=camera_id,
            path=Path(path_str),
            target_fps=target_fps,
            loop=loop,
        )

    if parsed.scheme in {"rtsp", "rtsps", "http", "https"}:
        from edge.capture.rtsp_source import RtspFrameSource  # noqa: PLC0415

        return RtspFrameSource(
            camera_id=camera_id,
            rtsp_url=source_uri,
            target_fps=target_fps,
        )

    raise ValueError(f"Unsupported source URI scheme: {source_uri!r}")
