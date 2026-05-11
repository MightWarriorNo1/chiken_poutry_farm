"""Camera source URI → type classification.

Used by the dashboard's `/api/cameras/sources` endpoint to group cameras by
the kind of frame source they use. Pure string inspection — no probing.

Categories:
  - `rtsp`       — rtsp:// or rtsps://
  - `http`       — http(s):// URLs (used for some IP cameras' MJPEG/JPEG feeds)
  - `usb`        — /dev/video*  (V4L2)
  - `csi`        — GStreamer pipeline starting with nvarguscamerasrc (Jetson CSI)
  - `gstreamer`  — any other GStreamer pipeline (advanced configs)
  - `file`       — file://... or a relative/absolute filesystem path
  - `unknown`    — anything we couldn't classify
"""

from __future__ import annotations

from urllib.parse import urlparse


def classify_source(source_uri: str) -> str:
    """Return one of: rtsp, http, usb, csi, gstreamer, file, unknown."""
    if not source_uri:
        return "unknown"

    s = source_uri.strip()
    lower = s.lower()

    # GStreamer pipelines are easy to spot: they contain " ! " element chains.
    # Check before URL parsing so e.g. "rtspsrc location=..." isn't misread.
    if " ! " in s or s.startswith(("nvarguscamerasrc", "rtspsrc ", "v4l2src ", "filesrc ")):
        if lower.startswith("nvarguscamerasrc"):
            return "csi"
        return "gstreamer"

    if lower.startswith(("rtsp://", "rtsps://")):
        return "rtsp"
    if lower.startswith(("http://", "https://")):
        return "http"

    parsed = urlparse(s)
    if parsed.scheme == "file":
        return "file"

    # /dev/video0, /dev/video1, ...
    if s.startswith("/dev/video") or (s.isdigit() and len(s) <= 2):
        return "usb"

    # Plain file path (relative or absolute) — the capture factory already
    # treats these as file:// sources.
    if s.startswith(("./", "/", "../")):
        return "file"

    return "unknown"


# Stable display labels for the UI.
TYPE_LABELS: dict[str, str] = {
    "rtsp": "RTSP",
    "http": "HTTP",
    "usb": "USB",
    "csi": "CSI",
    "gstreamer": "GStreamer",
    "file": "File",
    "unknown": "Unknown",
}


def type_label(kind: str) -> str:
    return TYPE_LABELS.get(kind, kind)
